import os
import re
import json
import time
import asyncio
import logging
from typing import Any, Optional, Dict, List, TypedDict
from decimal import Decimal
from datetime import date, datetime, time as dt_time


from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
from langchain_community.callbacks import get_openai_callback
from langsmith import traceable
from agent.utils.answerability import failure_response

from agent.utils.agent_config_loader import get_agent_node_config, merge_agent_config_with_defaults
from agent.utils.model_config_loader import load_model_config
from agent.utils.model_profiles import operation_config, configured_model_factory, response_text
from agent.state import AgentState
from agent.utils.prompts import get_answer_prompt, get_node_additional_instruction, ensure_json_directive
from agent.utils.openai_chat_kwargs import plain_completion_chat_kwargs, structured_tool_chat_kwargs
from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model, get_openai_compatible_base_url
from logger import logger
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.node_metrics import record_node_seconds
from agent.utils.deepseek_retry import ainvoke_structured_with_retry
from otel_tracing import track_time


# Moved imports to top level for performance
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

try:
    from groq import RateLimitError as GroqRateLimitError
except ImportError:
    GroqRateLimitError = Exception

class FinalAnswerOutput(TypedDict):
    """Structured output for the final answer node."""

    response: str
    """The natural-language answer to the user's question, formatted per the prompt guidelines."""

    is_answered: bool
    """True if the question was actually answered using the available data. False if the question
    could not be answered — e.g. the SQL result was empty/insufficient, the data source was
    restricted, a SQL/DB error was surfaced, or the response only asks for clarification or
    explains that the requested information is unavailable."""


def _get_cell(row: Any, col: str, idx: int) -> Any:
    """Extract a cell value from a row regardless of row format (dict / list / tuple / scalar)."""
    if isinstance(row, dict):
        return row.get(col)
    if isinstance(row, (list, tuple)):
        return row[idx] if idx < len(row) else None
    return row


def _build_result_payload_for_llm(
    rows: List[Any],
    columns: List[str],
    inline_limit: int,
    sample_size: int,
) -> str:
    """
    Build the SQL result payload that goes into the LLM prompt.

    Tiers:
      - 0 rows: short "no results" string.
      - <= inline_limit rows: full JSON.
      - > inline_limit rows: first inline_limit rows as JSON preview with a
        note that the full dataset is shown separately in the UI.
    """
    total = len(rows) if isinstance(rows, list) else 0

    if total == 0:
        return "No results returned by the SQL query."

    if total <= inline_limit:
        return json.dumps(rows)

    # Large result: send a preview so the LLM can render a table with the first N rows.
    preview = rows[:inline_limit]
    return (
        f"[{total} total rows — showing first {len(preview)} below. "
        f"The complete dataset is displayed as a separate table in the UI.]\n"
        + json.dumps(preview)
    )


def _extract_sql_limit(sql: str) -> Optional[int]:
    """Return the integer value of the LIMIT clause in a SQL query, or None if absent."""
    m = re.search(r'\bLIMIT\s+(\d+)\b', sql or '', re.IGNORECASE)
    return int(m.group(1)) if m else None


def _make_json_safe(value: Any) -> Any:
    # Numeric edge types
    if isinstance(value, Decimal):
        try:
            return float(value)
        except Exception:
            return str(value)

    # Date/time types
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()

    # Collections
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}

    # Bytes
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", errors="replace")

    # Primitives
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    # Fallback to string for unsupported types
    return str(value)


_DEFINITION_CHARS = int(os.getenv("FINAL_ANSWER_TABLE_DEFINITION_CHARS", "1500"))


def table_definitions_for_answer(descriptions: Any, selected_tables: Any) -> str:
    """The owner's descriptions of the tables this query read, for the answer prompt.

    SQL generation reads them, the answer did not: the sample agent's definitions say amounts
    are US dollars, yet answers said "the result does not specify a currency". Only the
    tables the query was built from are included, each capped, so the prompt stays small.
    """
    if not isinstance(descriptions, dict) or not descriptions:
        return "None provided."
    tables = [t for t in (selected_tables or []) if isinstance(t, str)] or list(descriptions)
    lines = []
    for table in tables:
        text_ = descriptions.get(table)
        if text_ is None:
            text_ = next((v for k, v in descriptions.items()
                          if k.split(".")[-1].lower() == table.split(".")[-1].lower()), None)
        if isinstance(text_, str) and text_.strip():
            lines.append(f"- {table}: {text_.strip()[:_DEFINITION_CHARS]}")
    return "\n".join(lines) or "None provided."


@traceable(run_type="chain", name="node_final_answer")
@track_time("Node: Final Answer")
async def node_final_answer(state: AgentState) -> AgentState:
    """Node that generates the final human-readable answer in parallel."""
    unavailable = failure_response(state)
    if unavailable:
        state.update(response=unavailable, is_answered=False, db_result=[], db_columns=None,
                     graph_json=None)
        return state
    logger.info(
        "[WF] step.start=final_answer_node | request_id=%s | session_id=%s",
        state.get("request_id"),
        state.get("session_id"),
    )
    
    agent_id = state.get("agent_id")
    owner_id = state.get("owner_id")
    rows = state.get("db_result") or []
    allowed = state.get("selected_tables") or []

    # Parallelize config and instruction fetching
    config_task = get_agent_node_config(agent_id, "final_answer_node")
    extra_task = get_node_additional_instruction(agent_id, "final_answer_node")
    
    node_config, extra = await asyncio.gather(config_task, extra_task)

    try:
        _prev = extra if extra and len(extra) <= 1000 else (extra[:1000] + "..." if extra else "")
        logger.info(f"Final answer node additional_instruction text_preview={_prev}")
    except Exception:
        pass
        
    prompt = get_answer_prompt(", ".join(allowed), additional_instruction=extra)

    rephrase_conf = operation_config("final_answer_node", node_config)

    model_name = rephrase_conf.get("model")
    provider = rephrase_conf.get("provider") 
    temperature = rephrase_conf.get("temperature", 0.0)

    # Get API keys with logging and source tracking
    api_key, key_type = await get_owner_api_key_for_provider(owner_id, provider, return_source=True)
    
    if api_key:
        logger.info(f"🚀 [LLM_CALL] Final Answer node initialized | owner_id: {owner_id} | model: {model_name} | source: {key_type}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] Final Answer node using default env credentials | owner_id: {owner_id} | model: {model_name}")

    # Dynamically select the model class
    provider_lower = provider.lower()
    # OpenAI-compatible providers (deepseek, minimax) → ChatOpenAI with a custom base_url.
    base_url = get_openai_compatible_base_url(provider_lower)

    if provider_lower == "groq":
        if ChatGroq is None:
            logger.error("ChatGroq not available but provider is groq")
            return {**state, "error": "ChatGroq not available"}
        ModelClass = ChatGroq
    elif provider_lower == "anthropic":
        if ChatAnthropic is None:
            logger.error("ChatAnthropic not available but provider is anthropic")
            return {**state, "error": "ChatAnthropic not available"}
        ModelClass = ChatAnthropic
    elif provider_lower in ("google", "gemini"):
        if ChatGoogleGenerativeAI is None:
            logger.error(f"ChatGoogleGenerativeAI not available but provider is {provider_lower}")
            return {**state, "error": f"ChatGoogleGenerativeAI not available for {provider_lower}"}
        ModelClass = ChatGoogleGenerativeAI
    else:
        ModelClass = ChatOpenAI

    # Structured output binds a tool/function, so OpenAI rejects reasoning_effort here —
    # use the tool-safe kwargs (no reasoning_effort) instead of plain_completion_chat_kwargs.
    ModelClass = configured_model_factory(rephrase_conf)

    openai_kwargs = (
        structured_tool_chat_kwargs(model_name)
        if provider_lower in ("openai", "azure_openai")
        else {}
    )
    if base_url:  # deepseek / minimax → OpenAI-compatible endpoint
        openai_kwargs = {**openai_kwargs, "base_url": base_url}
        if provider_lower == "deepseek":  # V4 defaults to slow thinking mode — disable it
            openai_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    base_model = ModelClass(model=model_name, temperature=temperature, api_key=api_key, **openai_kwargs) if api_key else ModelClass(model=model_name, temperature=temperature, **openai_kwargs)

    # Groq's default structured mode (strict) fails for gpt-oss models — it emits a generic
    # `json` tool call that isn't in request.tools ("tool_use_failed"), 400ing the request.
    # Use function_calling for Groq (mirrors router.py / db_router.py). Google keeps its default.
    if provider_lower in ("google", "gemini"):
        model = base_model.with_structured_output(FinalAnswerOutput)
    elif provider_lower == "deepseek":
        # DeepSeek V4 thinking model → json_mode (function_calling tool_choice is rejected).
        # json_mode requires the literal word "json" in the prompt.
        prompt = ensure_json_directive(prompt)
        def _make_deepseek_chain(_t: float):
            # Rebuilt per retry attempt so ainvoke_structured_with_retry can bump temperature
            # when DeepSeek returns an empty completion (see agent/utils/deepseek_retry.py).
            _bm = (ModelClass(model=model_name, temperature=_t, api_key=api_key, **openai_kwargs)
                   if api_key else ModelClass(model=model_name, temperature=_t, **openai_kwargs))
            return prompt | _bm.with_structured_output(FinalAnswerOutput, method="json_mode")
        model = base_model.with_structured_output(FinalAnswerOutput, method="json_mode")
    else:
        model = base_model.with_structured_output(FinalAnswerOutput, method="function_calling")
    
    safe_rows = _make_json_safe(rows)
    pandas_result = state.get("pandas_execution_result")
    pandas_plan = state.get("pandas_plan")

    db_columns = state.get("db_columns") or []
    columns_str = ", ".join(db_columns) if db_columns else "not available"

    _TOP_N_CAP = int(os.getenv("FINAL_ANSWER_TOP_N_CAP", "50"))
    # Cross-DB results are the already-combined answer set, and set-membership questions
    # (which X are in / missing from Y) need the LLM to see EVERY row or it miscounts —
    # a truncated preview produces confidently WRONG answers (e.g. "none in both" when 21
    # actually overlap) on any run where the pandas agent didn't compute the set logic.
    # Give cross-DB its own generous cap; the single-DB path is unchanged.
    _CROSS_DB_CAP = int(os.getenv("FINAL_ANSWER_CROSS_DB_ROW_CAP", "1000"))
    _PREVIEW_LIMIT = int(os.getenv("FINAL_ANSWER_INLINE_ROW_LIMIT", "10"))

    total_rows = len(safe_rows) if isinstance(safe_rows, list) else 0
    _cap = _CROSS_DB_CAP if state.get("cross_db") else _TOP_N_CAP

    # ≤ cap: LLM sees every row (no truncation).
    # > cap: LLM gets a preview; the full dataset is available via CSV export.
    effective_inline = total_rows if total_rows <= _cap else _PREVIEW_LIMIT
    result_json = _build_result_payload_for_llm(
        safe_rows, db_columns, effective_inline, 0
    )
    logger.info(
        "[FA] payload mode=%s | total_rows=%d | effective_inline=%d | request_id=%s",
        ("inline" if total_rows <= effective_inline else "preview"),
        total_rows, effective_inline, state.get("request_id"),
    )

    context = {
        "refined_query": state.get("refined_query", state.get("query", "")),
        "query": state.get("sql_query", ""),
        "result": result_json,
        "user_info": "",
        "db_columns": columns_str,
        "table_definitions": table_definitions_for_answer(
            state.get("table_descriptions"), state.get("selected_tables")),
    }

    if pandas_result:
        context["pandas_analysis"] = f"Pandas Agent Analysis:\n{pandas_result}\n\nPlan:\n{pandas_plan}"
        context["result"] = f"SQL Result:\n{result_json}\n\nPandas Analysis:\n{pandas_result}"

    # sql_exec refused to run the query because it read a table the operator switched off,
    # and cleared the SQL and rows. Without this the model sees only an empty result and
    # reports "no records found" — which reads as a fact about the data ("you have no
    # returns pending") when it is really a fact about access.
    denied = state.get("access_denied_tables")
    if denied:
        context["result"] = (
            "[Access denied] This question needs data from table(s) this agent is "
            "configured not to read: " + ", ".join(denied) + ". The query was NOT run, "
            "so there is no result. Tell the user plainly that you don't have access to "
            "the data needed to answer this, and that an administrator controls it under "
            "Tables & visibility in the database settings. Do NOT state or imply any "
            "figure, count, or that the answer is zero/empty — nothing was measured. "
            "Do not name columns or show SQL."
        )

    # Cross-DB results (multi-db-spec §11): the rows were combined in-application from several
    # databases. Explain the combined table's shape so the LLM reads provenance prefixes and
    # presence flags as join evidence instead of "missing data".
    # MUST come after the pandas_result override above, which replaces context["result"].
    if state.get("cross_db"):
        combine = state.get("cross_db_combine") or {}
        if combine.get("mode") == "stack":
            note = (
                "[Cross-database result] The databases' results could not be matched row-by-row "
                "(no common column), so they are STACKED together: the `source_database` column "
                "says which database each row came from. Treat each source's rows as its own "
                "independent answer — do not compare rows across sources line-by-line.\n\n"
            )
        else:
            join_col = combine.get("on") or "the shared key column"
            note = (
                "[Cross-database result] This table was produced by MATCHING rows from multiple "
                "databases (the databases cannot be joined in SQL, so the pairing happened after "
                f"querying each one). How to read it:\n"
                f"- `{join_col}` is the column the rows were matched on.\n"
                "- Every other column is prefixed with its source database: `<database>__<column>`.\n"
                "- A `<database>__present` column is match evidence: True means this key EXISTS "
                "in that database; empty/null means it does NOT exist there (this directly answers "
                "questions like 'which X are missing from Y').\n"
                "- Empty/null values in other prefixed columns mean that database had no matching "
                "row for that key.\n\n"
            )
        context["result"] = note + context["result"]
    
    start_time = time.time()
    with get_openai_callback() as cb:
        try:
            if provider_lower == "deepseek":
                # DeepSeek occasionally returns an empty json_mode completion → retry before
                # falling through to the plain-completion fallback below.
                ans_resp = await ainvoke_structured_with_retry(
                    _make_deepseek_chain, context,
                    base_temp=temperature, logger=logger, label="final_answer",
                )
            else:
                ans_resp = await (prompt | model).ainvoke(context)
        except Exception as struct_err:  # noqa: BLE001
            # Groq's structured output intermittently 400s ("tool_use_failed" / "Failed to
            # parse tool call arguments as JSON") when the answer is LONG — big markdown
            # tables inside a tool-argument string. Falling back to a plain completion turns
            # what was a request-killing 500 into a normal answer (is_answered inferred).
            logger.warning(
                "[FA] structured output failed (%s: %s); retrying as plain completion | request_id=%s",
                type(struct_err).__name__, str(struct_err)[:200], state.get("request_id"),
            )
            try:
                plain_resp = await (prompt | base_model).ainvoke(context)
                ans_resp = response_text(plain_resp)
            except Exception as plain_err:  # noqa: BLE001
                logger.error("[FA] plain completion also failed: %s", str(plain_err)[:300])
                ans_resp = ""

    # with_structured_output returns a dict (FinalAnswerOutput); be defensive in case a
    # provider returns a raw message (or the plain-completion fallback returned a string).
    if isinstance(ans_resp, dict):
        ans = ans_resp.get("response", "")
        is_answered = bool(ans_resp.get("is_answered", True))
    elif isinstance(ans_resp, str):
        ans = ans_resp
        is_answered = bool(ans.strip())
        if not ans:
            ans = ("I retrieved the data but ran into a temporary issue while writing the answer. "
                   "Please try the question again.")
    else:
        ans = response_text(ans_resp)
        is_answered = True

    execution_time = time.time() - start_time
    tokens_used = getattr(cb, "total_tokens", 0)
    input_tokens = getattr(cb, "prompt_tokens", getattr(cb, "input_tokens", 0))
    output_tokens = getattr(cb, "completion_tokens", getattr(cb, "output_tokens", 0))
    
    state["total_tokens"] = state.get("total_tokens", 0) + tokens_used

    # Same numbers, kept locally for the health event's per-node breakdown.
    record_node_seconds(
        state, "final_answer", execution_time, provider=provider, model=model_name,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=tokens_used,
        cached_input_tokens=getattr(cb, "prompt_tokens_cached", 0), key_type=key_type,
    )

    # Usage Tracking
    try:
        tracker = get_usage_tracker()
        k_type = key_type or "platform-key"
        
        await tracker.record_event(
            owner_id=owner_id,
            agent_id=agent_id,
            operation="llm_call",
            label="final_answer_generation",
            session_id=state.get("session_id"),
            request_id=state.get("request_id"),
            operation_id="final_answer",
            key_type=k_type,
            metadata={"provider": provider, "model": model_name, "temperature": temperature},
            metrics=[
                {"name": "input_tokens", "value": float(input_tokens or 0)},
                {"name": "output_tokens", "value": float(output_tokens or 0)},
                {"name": "total_tokens", "value": float(tokens_used)},
                {"name": "duration_ms", "value": float(execution_time * 1000.0)},
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to record final_answer usage event (non-blocking): {e}")
    
    state["response"] = ans
    state["is_answered"] = is_answered
    logger.info(
        "[WF] step.end=final_answer_node | request_id=%s | session_id=%s | response_len=%d | is_answered=%s | exec_time=%.2fs",
        state.get("request_id"),
        state.get("session_id"),
        len(ans or ""),
        is_answered,
        execution_time
    )
    return state


