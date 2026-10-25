from agent.utils.model_profiles import response_text
"""
DB Router node (multi-db-spec.md §5).

Selects which of an agent's databases should answer the current query, based on each
database's description. Runs after `router` (intent) and before `select_and_fewshots`
(table selection). Sets `state["db_id"]` and `state["runtime_db_details"]` so all
downstream nodes operate on the selected DB only.

Routing rules:
  * 0 routable (active + described) DBs  → keep whatever runtime_db_details the API
    provided (legacy/primary), log a warning.
  * exactly 1 routable DB                → select it deterministically (no LLM call).
  * 2+ routable DBs                       → one structured LLM call picks the db_id.
"""
import json
import time
from typing import List, Dict, Any, Optional

from langsmith import traceable
from pydantic import BaseModel

from agent.state import AgentState
from agent.utils.node_metrics import record_node_seconds
from agent.utils.usage_tracking import get_usage_tracker
from agent.db_utils.database_db_utils import get_all_databases
from logger import logger
from otel_tracing import track_time

try:
    from langchain_groq import ChatGroq
except ImportError:
    ChatGroq = None
try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None
from langchain_community.callbacks import get_openai_callback
from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI


class _DBChoice(BaseModel):
    db_id: str


class _RouteSelection(BaseModel):
    """One selected database plus the query IT should be asked (not the user's raw question)."""
    db_id: str
    query: str = ""        # self-contained request answerable from THIS database alone
    join_key: str = ""     # exact column name in THIS db's result that links it to the other
                           # selected DBs (cross-DB relate questions only; "" = nothing to match on)


class _RoutePlan(BaseModel):
    """Routing + per-DB planning in one shot. Usually exactly one selection.

    For cross-DB questions that RELATE entities across databases, each selection also carries
    `join_key`: the exact column (from that DB's shared keys) its result should be matched on.
    This is ADVISORY — the merge validates every declared key against the ACTUAL result columns
    and falls back to data-driven detection if any key is missing/wrong, so a model slip can
    never produce a worse merge than the heuristic-only path.
    """
    selections: List[_RouteSelection]


async def _build_llm(agent_id: Optional[str] = None, owner_id: Optional[str] = None):
    """Build the db_router LLM. Per-agent node override (chatbot_node_config) takes priority;
    falls back to model_config.json (db_router → router → select_table).

    Returns (llm, provider, model, key_type) so callers can pick the invocation style —
    structured output for providers that do it reliably, or a single plain-text call for Groq
    (whose tool/structured mode is unreliable for list schemas — see commit 7eaac33 / the
    LangSmith double-call) — and can attribute AND price the spend. The model is part of that:
    a usage event naming only the provider cannot be costed.

    Like every other LLM node, the owner's own key for this provider is used when they have
    one (BYOK) and the platform key otherwise. This node used to pass no key at all, so each
    SDK silently fell back to its env var and a multi-DB agent's routing call was always
    billed to the platform even for an owner who had paid for their own credentials.
    """
    from agent.utils.agent_config_loader import get_agent_node_config
    from agent.utils.model_profiles import operation_config, build_chat_model
    from agent.utils.owner_credential_utils import get_owner_api_key_for_provider
    conf = operation_config("db_router", await get_agent_node_config(agent_id, "db_router"))
    api_key, key_type = await get_owner_api_key_for_provider(owner_id, conf["provider"], return_source=True)
    return build_chat_model(conf, api_key=api_key), conf["provider"], conf["model"], key_type


def _parse_ids_from_text(text: str, ordered_ids: List[str]) -> List[str]:
    """Extract valid db_ids mentioned in free-text output, preserving the given (routable) order."""
    out: List[str] = []
    for vid in ordered_ids:
        if vid in text and vid not in out:
            out.append(vid)
    return out


def _select_runtime(state: AgentState, db: Dict[str, Any]) -> AgentState:
    """Set the selected db into state, mapping the candidate dict to runtime_db_details."""
    state["db_id"] = db.get("db_id")
    state["runtime_db_details"] = {
        "db_id": db.get("db_id"),
        "db_host": db.get("db_host"),
        "db_name": db.get("db_name"),
        "db_user": db.get("db_user"),
        "db_password": db.get("db_password"),
        "db_port": db.get("db_port"),
        "db_engine": db.get("db_engine"),
    }
    return state


@traceable(run_type="chain", name="node_db_router")
@track_time("Node: DB Router")
async def node_db_router(state: AgentState) -> AgentState:
    """Pick the database for this query and pin runtime_db_details + db_id into state."""
    agent_id = state.get("agent_id")
    request_id = state.get("request_id")
    logger.info("[WF] step.start=db_router | request_id=%s | agent_id=%s", request_id, agent_id)

    if not agent_id:
        return state

    try:
        databases: List[Dict[str, Any]] = await get_all_databases(agent_id, active_only=True)
    except Exception as e:
        logger.warning("[db_router] could not load databases (%s); keeping provided runtime DB", e)
        return state

    state["available_databases"] = [
        {"db_id": d.get("db_id"), "description": d.get("description")}
        for d in databases
    ]

    routable = [d for d in databases if (d.get("description") or "").strip()]

    # 0 routable → keep whatever the API provided (primary/legacy).
    if not routable:
        if databases:
            logger.warning(
                "[db_router] no active DB has a description for agent %s; "
                "falling back to first active DB (routing degraded)", agent_id
            )
            return _select_runtime(state, databases[0])
        logger.warning("[db_router] no active databases for agent %s", agent_id)
        return state

    # 1 routable → deterministic.
    if len(routable) == 1:
        logger.info("[db_router] single routable DB → %s", routable[0].get("db_id"))
        return _select_runtime(state, routable[0])

    # 2+ routable → ONE LLM call does routing AND per-DB query planning (spec §11).
    # The structured output is [{db_id, query}]: each selected database gets a
    # query tailored to what IT holds — the user's raw question is never sent to a database that
    # only has part of the answer. When >1 DB is selected this IS the decompose plan, so no
    # separate db_planner call is needed.
    refined_query = state.get("refined_query") or state.get("query", "")
    # Schema linking: real table names + key-column placement per DB (cached introspection),
    # so the plan references EXISTING identifiers instead of guessing from prose descriptions.
    try:
        from agent.utils.db_routing_hints import get_routing_hints
        hints = await get_routing_hints(routable)
    except Exception as e:
        logger.warning("[db_router] routing hints unavailable (%s); planning from descriptions only", e)
        hints = {}
    catalog = []
    for d in routable:
        entry = {"db_id": d["db_id"], "description": d.get("description", "")}
        if hints.get(d["db_id"]):
            entry["tables_and_keys"] = hints[d["db_id"]]
        catalog.append(entry)
    valid_ids = {d["db_id"] for d in routable}
    ordered_ids = [d["db_id"] for d in routable]
    by_id = {d["db_id"]: d for d in routable}
    prompt = (
        "You route a user's question to the database(s) required to answer it, and write the "
        "query each selected database should be asked.\n\n"
        "Rules:\n"
        "1. MOST questions need EXACTLY ONE database. Select MULTIPLE only when the question "
        "genuinely requires COMBINING data that lives in different databases (e.g. a value from "
        "one database joined with a value from another). When in doubt, select one.\n"
        "2. For each selected database write `query`: a self-contained natural-language request "
        "answerable from THAT database alone, per its description and `tables_and_keys`. Never "
        "pass the user's whole question to a database that only holds part of the answer — ask "
        "each database only for its part. When steering toward specific data, mention ONLY "
        "tables that appear in that database's `tables_and_keys` list.\n"
        "3. When MULTIPLE databases are selected AND the question relates entities across them "
        "(per-owner / per-agent / per-session comparisons, 'which X are missing from Y', etc.): "
        "every `query` MUST also ask for the common identifier column that links the results — "
        "choose an EXACT column name from the `shared keys:` part of BOTH selected databases' "
        "`tables_and_keys` (never invent or rename it), so both results contain that column. "
        "Results must be COMPLETE over that column — never 'top N' unless the user asked. "
        "Also set each selection's `join_key` to that EXACT column name (as it will appear in "
        "that database's result), so the merge pairs rows on it instead of guessing.\n"
        "4. When the question just needs SEPARATE facts from each database (nothing to match "
        "row-by-row), each `query` simply fetches its own part — no common column required, "
        "and leave `join_key` empty.\n\n"
        f"Databases:\n{json.dumps(catalog, indent=2)}\n\n"
        f"User question: {refined_query}\n\n"
        "Return the routing plan."
    )
    owner_id = state.get("owner_id")
    llm, provider, model_name, key_type = await _build_llm(agent_id, owner_id)

    _route_start = time.time()

    selections: List[Dict[str, str]] = []

    # Both attempts run inside one callback so the fallback's tokens are counted too: this
    # node can legitimately make two LLM calls, and pricing only the first would understate
    # exactly the runs that went wrong. Non-OpenAI providers may report nothing through this
    # callback, the same as every other node using it — LangSmith stays the backstop.
    with get_openai_callback() as cb:
        # Structured attempt (function_calling works on Groq for object-list schemas — the old
        # failures were with the ids-only schema; db_planner ran this shape reliably in prod).
        try:
            result = await llm.with_structured_output(_RoutePlan, method="function_calling").ainvoke(prompt)
            if result and result.selections:
                selections = [
                    {"db_id": s.db_id, "query": (s.query or "").strip(), "join_key": (s.join_key or "").strip()}
                    for s in result.selections
                ]
        except Exception as e:
            logger.warning("[db_router] structured routing failed (%s); trying plain-text JSON fallback", e)

        # Fallback: same content as plain-text JSON.
        if not selections:
            try:
                resp = await llm.ainvoke(
                    prompt + '\n\nReturn ONLY JSON: {"selections":[{"db_id":"...","query":"...","join_key":"..."}]}'
                )
                text = response_text(resp)
                if text.startswith("```"):
                    text = text.strip("`").replace("json\n", "", 1).strip()
                parsed = json.loads(text)
                selections = [
                    {"db_id": s.get("db_id", ""), "query": (s.get("query") or "").strip(),
                     "join_key": (s.get("join_key") or "").strip()}
                    for s in (parsed.get("selections") or [])
                ]
            except Exception as e:
                logger.warning("[db_router] plain-text routing failed (%s); trying bare id match", e)

    tokens_used = getattr(cb, "total_tokens", 0) or 0
    input_tokens = getattr(cb, "prompt_tokens", None)
    output_tokens = getattr(cb, "completion_tokens", None)
    state["total_tokens"] = state.get("total_tokens", 0) + tokens_used

    # Keep only valid, deduped selections (order preserved).
    seen: set = set()
    selections = [s for s in selections
                  if s["db_id"] in valid_ids and not (s["db_id"] in seen or seen.add(s["db_id"]))]

    # Last resorts: bare id match from whatever text we have, else first routable DB.
    if not selections:
        selections = [{"db_id": routable[0]["db_id"], "query": "", "join_key": ""}]

    _route_seconds = time.time() - _route_start
    record_node_seconds(state, "db_router", _route_seconds, provider=provider, model=model_name,
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        total_tokens=tokens_used, key_type=key_type,
                        cached_input_tokens=getattr(cb, "prompt_tokens_cached", 0))

    # Usage event: this routing call went unrecorded entirely, so on a multi-DB agent the
    # spend was invisible to billing rather than merely misattributed to the platform.
    try:
        tracker = get_usage_tracker()
        await tracker.record_event(
            owner_id=owner_id,
            agent_id=agent_id,
            operation="llm_call",
            label="db_routing",
            session_id=state.get("session_id"),
            request_id=request_id,
            operation_id="db_router",
            key_type=key_type,
            metadata={"provider": provider, "model": model_name},
            metrics=[
                {"name": "input_tokens", "value": float(input_tokens or 0)},
                {"name": "output_tokens", "value": float(output_tokens or 0)},
                {"name": "total_tokens", "value": float(tokens_used)},
                {"name": "duration_ms", "value": float(_route_seconds * 1000.0)},
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to record db_router usage event (non-blocking): {e}")

    # Multi-DB requires a usable per-DB query on every selection; degrade to single-DB otherwise.
    if len(selections) > 1 and not all(s["query"] for s in selections):
        logger.warning("[db_router] multi-DB plan missing per-DB queries; degrading to single DB")
        selections = selections[:1]

    # Single DB selected → existing single-DB path, byte-for-byte unchanged behaviour
    # (refined_query keeps driving downstream; the tailored query is not substituted here to
    # avoid any drift on the battle-tested single-DB path).
    if len(selections) == 1:
        logger.info(
            "[WF] step.end=db_router | request_id=%s | selected_db=%s | n_candidates=%d",
            request_id, selections[0]["db_id"], len(routable),
        )
        return _select_runtime(state, by_id[selections[0]["db_id"]])

    # 2+ DBs selected → cross-DB: the selections ARE the decompose plan (fan-out → merge).
    # No key/how here by design: the merge detects the relationship from the actual result
    # columns (common column → join; none → stack side-by-side).
    state["cross_db"] = True
    state["selected_dbs"] = [by_id[s["db_id"]] for s in selections]
    state["cross_db_plan"] = {
        "sub_questions": [
            {"db_id": s["db_id"], "question": s["query"], "join_key": s.get("join_key", "")}
            for s in selections
        ],
    }
    # Seed runtime_db_details/db_id with the first DB for observability/safety; the cross-DB
    # branch bypasses the single-DB select/sql_gen path and uses selected_dbs instead.
    _select_runtime(state, by_id[selections[0]["db_id"]])
    logger.info(
        "[WF] step.end=db_router | request_id=%s | cross_db=True | plan=%s | n_candidates=%d",
        request_id, [s["db_id"] for s in selections], len(routable),
    )
    return state
