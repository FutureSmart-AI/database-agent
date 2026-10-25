import os
import json
import time
import asyncio
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from langchain_core.messages import AIMessage, HumanMessage
from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
from langchain_community.callbacks import get_openai_callback
from langchain_community.utilities import sql_database
from langsmith import traceable

from agent.utils.agent_config_loader import get_agent_node_config, merge_agent_config_with_defaults
from agent.utils.model_config_loader import load_model_config
from agent.utils.model_profiles import operation_config, configured_model_factory, ModelConfigurationError, response_text
from agent.state import AgentState
from agent.utils.prompts import get_sql_query_prompt, get_node_additional_instruction
from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model, get_openai_compatible_base_url
from logger import logger
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.node_metrics import record_node_seconds
from agent.utils.deepseek_retry import ainvoke_structured_with_retry
from otel_tracing import track_time
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs
from agent.utils.answerability import SQLQuerySchema, apply_sql_decision

load_dotenv()

# SQL generation is deterministic work: the same question against the same schema
# should produce the same query. Sampling gives a different query each run, which
# makes regressions unmeasurable — one benchmark run varied every one of 8 questions
# across 3 attempts, and the same question alternated between correct SQL and SQL
# with a spurious LIMIT.
DEFAULT_SQL_GEN_TEMPERATURE = 0.0

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

def strip_code_fence(s: str | None) -> str:
    if s is None:
        return ""
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.replace("sql\n", "").replace("SQL\n", "")
    return s.strip()


def _past_messages_to_lc_messages(
    past_messages: List[Dict[str, Any]] | None, *, max_chars_per_msg: int = 12000
) -> List[HumanMessage | AIMessage]:
    """Turn stored session history into chat messages for SQL generation context."""
    out: List[HumanMessage | AIMessage] = []
    for m in past_messages or []:
        role = (m.get("role") or "").strip().lower()
        # if role != "user":
        #     # User turns carry follow-up constraints; assistant long-form responses add noise.
        #     continue
        content = m.get("content") or ""
        if len(content) > max_chars_per_msg:
            content = content[:max_chars_per_msg] + "\n...[truncated]"
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _sanitize_sql(text: str) -> str:
    s = strip_code_fence(text)
    # Remove accidental prefixes like "SQL Query:" or "Query:"
    prefixes = ["SQL Query:", "Sql Query:", "sql query:", "Query:"]
    for p in prefixes:
        if s.strip().startswith(p):
            s = s.strip()[len(p):].strip()
            break
    return s


@traceable(run_type="chain", name="node_sql_gen")
@track_time("Node: SQL Generation")
async def node_sql_gen(state: AgentState) -> AgentState:
    """Node that generates SQL queries from natural language in parallel."""
    logger.info(
        "[WF] step.start=sql_gen | request_id=%s | session_id=%s",
        state.get("request_id"),
        state.get("session_id"),
    )
    
    # Selection denial uses the canonical terminal state; do not restart work.
    if state.get("access_denied_tables") or state.get("access_policy_error"):
        return state

    agent_id = state.get("agent_id")
    user_id = state.get("user_id")
    owner_id = state.get("owner_id")
    tables = state.get("selected_tables") or []
    runtime_db = state.get("runtime_db_details") or {}
    refined_query = state.get("refined_query", state.get("query", ""))

    # SQLDatabase.get_table_info samples source rows. Verify fresh table policy
    # before that introspection OR cached value/suffix preparation, not only
    # after the model generates SQL. Execution reloads the policy again.
    from agent.utils.table_access import deny_table_access
    from agent.utils.sampling_policy import get_table_visibility, blocked_table_names
    try:
        permitted, excluded = await get_table_visibility(
            user_id, agent_id, runtime_db.get("db_id") or state.get("db_id"))
        blocked = blocked_table_names(tables, permitted, excluded)
    except Exception as error:
        logger.error("sql_gen: table access policy could not be verified (%s)", type(error).__name__)
        return deny_table_access(state, policy_error=True)
    if blocked:
        return deny_table_access(state, tables=blocked)

    # Track retry and inject previous error context so the LLM generates a different query
    prev_error = state.get("sql_error")
    prev_sql = state.get("sql_query")
    if prev_error:
        state["retry_count"] = state.get("retry_count", 0) + 1
        logger.info(
            "[WF] sql_gen retry #%d | request_id=%s | prev_error=%s",
            state["retry_count"],
            state.get("request_id"),
            prev_error,
        )

    # Below this many permitted tables, selection is skipped entirely and the
    # model is shown everything the agent may read. Table selection exists so
    # the prompt does not grow with the size of the schema; under a dozen
    # tables there is nothing to save, and plenty to lose.
    FULL_SCHEMA_TABLE_LIMIT = 12

    def _widen_table_set(inspector, chosen, permitted):
        """Give the model the tables `chosen` is joined to, not just `chosen`.

        select_table runs before anything reads the schema and picks tables from
        the written descriptions alone. Whatever it leaves out, this node never
        sees - not the columns, not that the table exists - and there is no way
        back: sql_gen cannot ask for a table it turns out to need.

        That produced wrong answers rather than errors. Asked for MRR, the
        selector returned only the subscription and plan tables, so the SQL
        could not exclude the company's own internal accounts - the column
        marking them sits on a table that was never offered. The query was
        valid, ran without complaint, and overstated revenue by 11%.

        Two ways out, cheapest first:

        Under FULL_SCHEMA_TABLE_LIMIT tables, hand over everything permitted.
        No inference, no blind spot, and the prompt stays small because the
        schema is small. Most agents connect to a database this size.

        Above it, widen one hop from what was chosen. Declared foreign keys are
        the schema stating the relationship itself, but they cannot be relied
        on: this project's own benchmark database declares three of six, and
        application schemas built through an ORM frequently declare none. So a
        column named for another permitted table (`account_id` beside
        `accounts`) counts as the same evidence. Only the parent direction is
        followed - the tables a chosen row is qualified BY - because that is
        where filters like "not internal" and "not free" live, and because
        following children out of a hub table drags in the whole database.

        Widening is confined to `permitted`, so a table excluded in the
        dashboard stays excluded, and returns `chosen` untouched when
        permissions cannot be read. It fails closed.
        """
        if not permitted:
            return list(chosen)

        if len(permitted) <= FULL_SCHEMA_TABLE_LIMIT:
            if set(permitted) != set(chosen):
                logger.info(
                    "[sql_gen] small schema (%d tables): showing all permitted, not just %s",
                    len(permitted), sorted(chosen),
                )
            return list(permitted)

        by_lower = {t.lower(): t for t in permitted}
        picked = {t.lower() for t in chosen}
        added = set()

        def _match(stem):
            """`account_id` -> accounts. Tries the stem, then its plural."""
            for cand in (stem, stem + "s", stem + "es"):
                if cand in by_lower and cand not in picked:
                    return cand
            return None

        for table in chosen:
            try:
                for fk in inspector.get_foreign_keys(table):
                    ref = (fk.get("referred_table") or "").lower()
                    if ref in by_lower and ref not in picked:
                        added.add(ref)
                for col in inspector.get_columns(table):
                    name = (col.get("name") or "").lower()
                    if name.endswith("_id"):
                        hit = _match(name[:-3])
                        if hit:
                            added.add(hit)
            except Exception:
                continue

        if added:
            logger.info(
                "[sql_gen] widened one hop: %s + %s", sorted(picked), sorted(added)
            )
        keep = picked | added
        return [t for t in permitted if t.lower() in keep]

    # --- Step 1: Parallel setup ---
    async def get_table_info_from_db():
        if not runtime_db or not tables:
            return "", list(tables)
        try:
            db_engine = runtime_db.get("db_engine", "mysql")
            if db_engine == "mysql":
                uri = (
                    f"mysql+pymysql://{runtime_db['db_user']}:{runtime_db['db_password']}@"
                    f"{runtime_db['db_host']}/{runtime_db['db_name']}"
                )
            elif db_engine == "postgresql":
                uri = (
                    f"postgresql+psycopg2://{runtime_db['db_user']}:{runtime_db['db_password']}@"
                    f"{runtime_db['db_host']}:{runtime_db.get('db_port', 5432)}/{runtime_db['db_name']}"
                )
            else:
                return ""
            
            # Schema introspection is blocking (sync SQLAlchemy + network round-trips). Run it
            # in a worker thread so parallel cross-DB fan-out branches introspect their schemas
            # SIMULTANEOUSLY instead of serializing on the event loop.
            def _introspect(include):
                from sqlalchemy import create_engine, inspect as sa_inspect
                widened = include
                try:
                    widened = _widen_table_set(
                        sa_inspect(create_engine(uri)), include, permitted
                    )
                except Exception as fk_err:
                    logger.warning("[sql_gen] table widening skipped: %s", fk_err)
                db = sql_database.SQLDatabase.from_uri(
                    uri, sample_rows_in_table_info=1, view_support=True, include_tables=widened
                )
                return db.get_table_info(), widened

            return await asyncio.to_thread(_introspect, tables)
        except Exception as e:
            logger.warning(f"Failed to fetch table info: {e}")
            return "", list(tables)

    async def get_suffix():
        if not agent_id or not runtime_db:
            return ""
        try:
            from agent.utils.high_cardinality_utils import get_suffix_string
            return await get_suffix_string(
                user_id,
                agent_id,
                {"db_details": runtime_db},
                refined_query,
                tables,
                owner_id=owner_id,
                db_id=state.get("db_id"),
            )
        except ModelConfigurationError:
            raise
        except Exception as e:
            logger.error(f"sql_gen: Failed to compute suffix_string: {e}")
            return ""

    async def get_column_notes():
        """Per-column descriptions for the tables this query will touch.

        These are written in the dashboard and were stored but never read at
        query time - nothing under agent/ loaded them, so a customer could
        document `is_internal` as "our own test accounts, not customers" and
        the model never saw it. Only the tables actually selected are included,
        so the prompt does not grow with the size of the schema.
        """
        if not tables:
            return ""
        try:
            from knowledge.db_utils.column_description_db_utils import (
                get_all_column_descriptions,
            )
            # db_router pins db_id into both places; the cross-DB fan-out
            # builds its own runtime_db_details, so fall back to state.
            resp = await get_all_column_descriptions(
                user_id, agent_id,
                db_id=runtime_db.get("db_id") or state.get("db_id"),
            )
            records = (resp or {}).get("records") or []
            wanted = {t.lower() for t in tables}
            lines = []
            for rec in records:
                tname = rec.get("table_name") or ""
                if tname.lower() not in wanted:
                    continue
                cols = rec.get("column_descriptions") or {}
                if isinstance(cols, str):
                    cols = json.loads(cols)
                for col, desc in cols.items():
                    if desc and str(desc).strip():
                        lines.append("- %s.%s: %s" % (tname, col, str(desc).strip()))
            if not lines:
                return ""
            logger.info(
                "[sql_gen] column descriptions loaded | agent_id=%s tables=%d lines=%d",
                agent_id, len(wanted), len(lines),
            )
            return "\n\nColumn notes:\n" + "\n".join(lines)
        except Exception as e:
            # Never let an optional annotation break SQL generation.
            logger.warning("[sql_gen] could not load column descriptions: %s", e)
            return ""

    # Execute all setup tasks in parallel
    setup_tasks = [
        get_table_info_from_db(),
        get_suffix(),
        get_agent_node_config(agent_id, "sql_gen"),
        get_node_additional_instruction(agent_id, "sql_gen"),
        get_column_notes(),
    ]

    table_info_result, suffix_string, node_config, extra, column_notes = await asyncio.gather(*setup_tasks)
    table_info, widened_tables = table_info_result

    # The widened set is what the model was actually shown, so it is what the
    # question's table list should say. final_answer refuses an answer whose SQL
    # touches a table outside this list, and used to reject correct results for
    # joining a table the selector had missed - it held the right row and told
    # the user the data was restricted. Recording the truth here removes that.
    if widened_tables and set(widened_tables) != set(tables):
        tables = list(widened_tables)
        state["selected_tables"] = tables

    # Appended to suffix_string because it is already a plain string that this
    # node extends (see the retry hint below); table_descriptions may be a dict.
    if column_notes:
        suffix_string = (suffix_string or "") + column_notes

    # On retry, append the previous failure so the LLM knows what to avoid
    if prev_error and prev_sql:
        error_hint = (
            f"\n\nPREVIOUS SQL ATTEMPT FAILED — generate a DIFFERENT query:\n"
            f"Failed SQL:\n{prev_sql}\n"
            f"Execution error: {prev_error}"
        )
        suffix_string = (suffix_string or "") + error_hint

    # Determine SQL dialect
    engine = (runtime_db.get("db_engine") or os.getenv("DB_ENGINE") or "mysql").lower()
    sql_dialect = "MySQL" if engine == "mysql" else ("PostgreSQL" if engine == "postgresql" else "SQL")
    few_shots = state.get("few_shot_examples") or ""

    # Build prompt. Follow-up handling rules are only relevant when prior conversation exists.
    has_history = bool(state.get("past_messages"))
    prompt = get_sql_query_prompt(
        suffix_string=suffix_string,
        sql_dialect=sql_dialect,
        few_shot_examples=few_shots,
        user_info="",
        additional_instruction=extra,
        has_history=has_history,
    )

    # Determine model config
    sql_gen_conf = operation_config("sql_gen", node_config)

    model_name = sql_gen_conf["model"]
    provider = sql_gen_conf["provider"]
    temperature = sql_gen_conf.get("temperature")
    if temperature is None:
        temperature = DEFAULT_SQL_GEN_TEMPERATURE

    # Get API key and metadata once
    api_key, key_type = await get_owner_api_key_for_provider(owner_id, provider, return_source=True)
    
    if api_key:
        logger.info(f"🚀 [LLM_CALL] SQL Gen node initialized | owner_id: {owner_id} | model: {model_name} | source: {key_type}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] SQL Gen node using default env credentials | owner_id: {owner_id} | model: {model_name}")

    # Dynamically select the model class
    provider_lower = provider.lower()
    # OpenAI-compatible providers (deepseek, minimax) go through ChatOpenAI with a custom base_url.
    base_url = get_openai_compatible_base_url(provider_lower)
    is_groq = False

    if provider_lower == "groq":
        if ChatGroq is None:
            logger.error("ChatGroq not available but provider is groq")
            return {**state, "error": "ChatGroq not available"}
        ModelClass = ChatGroq
        is_groq = True
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

    ModelClass = configured_model_factory(sql_gen_conf)

    openai_kwargs = (
        structured_tool_chat_kwargs(model_name)
        if provider_lower in ("openai", "azure_openai")
        else {}
    )
    if base_url:  # deepseek / minimax → OpenAI-compatible endpoint
        openai_kwargs = {**openai_kwargs, "base_url": base_url}
        if provider_lower == "deepseek":  # V4 defaults to slow thinking mode — disable it
            openai_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    if is_groq:
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key).with_structured_output(SQLQuerySchema, method="json_mode") if api_key else ModelClass(model=model_name, temperature=temperature).with_structured_output(SQLQuerySchema, method="json_mode")
    elif provider_lower == "deepseek":
        # DeepSeek V4 is a thinking model: rejects function_calling tool_choice — use json_mode.
        def _make_deepseek_chain(_t: float):
            # Rebuilt per retry attempt so ainvoke_structured_with_retry can bump temperature
            # when DeepSeek returns an empty completion (see agent/utils/deepseek_retry.py).
            _llm = (ModelClass(model=model_name, temperature=_t, api_key=api_key, **openai_kwargs)
                    if api_key else ModelClass(model=model_name, temperature=_t, **openai_kwargs))
            return prompt | _llm.with_structured_output(SQLQuerySchema, method="json_mode")
        def _make_deepseek_plain(_t: float):
            # Plain (non-structured) completion fallback. The json_mode structured wrapper is the
            # fragile part — DeepSeek sometimes returns an empty body for it — so a bare completion
            # (the prompt already asks for a JSON object with `generated_query`) usually returns
            # text we can extract the SQL from, turning a persistent empty into a real answer.
            return prompt | (ModelClass(model=model_name, temperature=_t, api_key=api_key, **openai_kwargs)
                             if api_key else ModelClass(model=model_name, temperature=_t, **openai_kwargs))
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key, **openai_kwargs).with_structured_output(SQLQuerySchema, method="json_mode") if api_key else ModelClass(model=model_name, temperature=temperature, **openai_kwargs).with_structured_output(SQLQuerySchema, method="json_mode")
    elif provider_lower == "google":
        # Default method ("function_calling") relies on Gemini reliably issuing a tool call;
        # gemini-3-flash-preview instead sometimes answers in plain text (JSON in a markdown
        # fence), which PydanticToolsParser can't see since it only reads tool_calls, silently
        # producing an empty SQL. "json_schema" binds response_mime_type/response_json_schema
        # on the API call itself and parses the text content, matching how Gemini actually answers.
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key).with_structured_output(SQLQuerySchema, method="json_schema") if api_key else ModelClass(model=model_name, temperature=temperature).with_structured_output(SQLQuerySchema, method="json_schema")
    else:
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key, **openai_kwargs).with_structured_output(SQLQuerySchema, method="function_calling") if api_key else ModelClass(model=model_name, temperature=temperature, **openai_kwargs).with_structured_output(SQLQuerySchema, method="function_calling")

    sql_chat_history = _past_messages_to_lc_messages(state.get("past_messages"))

    # Execute LLM call
    start_time = time.time()
    sql_invoke_inputs = {
        "messages": sql_chat_history,
        "refined_query": refined_query,
        "table_description": state.get("table_descriptions") or "",
        "table_info": table_info,
        "few_shot_examples": few_shots,
        "suffix_string": suffix_string,
    }
    with get_openai_callback() as cb:
        if provider_lower == "deepseek":
            # DeepSeek occasionally returns an empty json_mode completion → retry before it propagates.
            try:
                result = await ainvoke_structured_with_retry(
                    _make_deepseek_chain, sql_invoke_inputs,
                    base_temp=temperature, logger=logger, label="sql_gen",
                )
            except Exception as struct_err:  # noqa: BLE001 — persistent empty/parse failure
                # Structured json_mode empty even after retries → fall back to a plain completion
                # and extract the SQL, instead of letting OutputParserException crash the request.
                logger.warning(
                    "[sql_gen] structured json_mode failed after retries (%s: %s); "
                    "falling back to plain completion | request_id=%s",
                    type(struct_err).__name__, str(struct_err)[:200], state.get("request_id"),
                )
                plain_resp = await _make_deepseek_plain(max(temperature, 0.4)).ainvoke(sql_invoke_inputs)
                _txt = response_text(plain_resp)
                result = {}
                if _txt:
                    _cand = strip_code_fence(_txt)
                    try:
                        _parsed = json.loads(_cand)
                        result = _parsed if isinstance(_parsed, dict) else {}
                    except Exception:
                        # Raw SQL alone has no schema-support decision; do not bypass it.
                        result = {}
        else:
            result = await (prompt | model).ainvoke(sql_invoke_inputs)
    
    execution_time = time.time() - start_time
    tokens_used = getattr(cb, "total_tokens", 0)
    input_tokens = getattr(cb, "prompt_tokens", None)
    output_tokens = getattr(cb, "completion_tokens", None)
    
    state["total_tokens"] = state.get("total_tokens", 0) + tokens_used

    # Same numbers, kept locally for the health event. A retry re-enters this node, so
    # record_node_seconds merges the second attempt into one sql_gen entry with calls=2.
    record_node_seconds(
        state, "sql_gen", execution_time, provider=provider, model=model_name,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=tokens_used,
        cached_input_tokens=getattr(cb, "prompt_tokens_cached", 0), key_type=key_type,
    )

    # Record usage event
    try:
        tracker = get_usage_tracker()
        k_type = key_type or "platform-key"
        await tracker.record_event(
            owner_id=owner_id,
            agent_id=agent_id,
            operation="llm_call",
            label="sql_generation",
            session_id=state.get("session_id"),
            request_id=state.get("request_id"),
            operation_id="sql_gen",
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
        logger.warning(f"Failed to record sql_gen usage event (non-blocking): {e}")

    try:
        state["sql_query"] = _sanitize_sql(apply_sql_decision(state, result))
    except (ValueError, TypeError):
        state.update(sql_query="", sql_error="SQL generation returned a malformed schema-support decision.",
                     db_result=[], db_columns=None, answerability_error=None)
    if state.get("answerability_error"):
        # The model's own reason is the only record of why a question was refused.
        logger.warning(
            "[sql_gen] answerable=false | request_id=%s | agent_id=%s | tables=%s | reason=%s",
            state.get("request_id"), agent_id, tables, str(state["answerability_error"])[:500],
        )
    logger.info(
        "[WF] step.end=sql_gen | request_id=%s | action=%s | exec_time=%.2fs | has_sql=%s",
        state.get("request_id"),
        state.get("action"),
        execution_time,
        bool(state.get("sql_query")),
    )
    return state


