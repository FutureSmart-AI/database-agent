from agent.utils.model_profiles import ModelConfigurationError
import asyncio
import os
import json
import logging
from typing import Dict, List, Tuple, Any, Optional
from dotenv import load_dotenv

from langsmith import traceable
from agent.state import AgentState
from agent.utils.langchain_utils import get_table_descriptions_and_selected_tables  
from agent.utils.langchain_utils import select_tables
from agent.utils.agent_config_loader import get_agent_node_config
from agent.utils.node_metrics import measure_node_calls
from agent.utils.few_shot_utils import get_few_shot_service
from agent.utils.prompts import build_few_shot_examples_string
from logger import logger
from otel_tracing import track_time

load_dotenv()

@traceable(run_type="tool", name="node_select_and_fewshots")
@track_time("Node: Select Table and Few-Shots")
async def node_select_and_fewshots(state: AgentState) -> AgentState:
    """Verify selected table scope before retrieving few-shot examples."""
    from agent.utils.table_access import deny_table_access
    if state.get("access_policy_error") or state.get("access_denied_tables"):
        return deny_table_access(state, tables=state.get("access_denied_tables"),
                                 policy_error=state.get("access_policy_error", False))
    logger.info(
        "[WF] step.start=select_and_fewshots | request_id=%s | session_id=%s",
        state.get("request_id"),
        state.get("session_id"),
    )
    refined_query = state.get("refined_query") or state.get("query", "")
    user_id = state.get("user_id")
    agent_id = state.get("agent_id")
    owner_id = state.get("owner_id")
    session_id = state.get("session_id")
    request_id = state.get("request_id")
    db_id = state.get("db_id")  # multi-DB: selected by db_router (None → helpers use primary)

    # The catalog must obey the same identity-bound policy as sampling/execution.
    # Verify before starting selection, few-shot retrieval or any source work.
    from agent.utils.table_access import (
        get_table_visibility, blocked_table_names, deny_table_access,
        TableAccessPolicyError,
    )
    db_id = (state.get("runtime_db_details") or {}).get("db_id") or db_id
    try:
        permitted, excluded = await get_table_visibility(user_id, agent_id, db_id)
        if not permitted:
            return deny_table_access(state, tables=excluded)
        preselected = state.get("selected_tables")
        if preselected:
            blocked = blocked_table_names(preselected, permitted, excluded)
            if blocked:
                return deny_table_access(state, tables=blocked)
    except Exception as error:
        logger.warning("Selection policy unavailable (%s)", type(error).__name__)
        return deny_table_access(state, policy_error=True)

    def scoped_catalog(descriptions):
        if not isinstance(descriptions, dict):
            raise TableAccessPolicyError("Table description catalog is invalid")
        return {name: description for name, description in descriptions.items()
                if not blocked_table_names([name], permitted, excluded)}

    async def get_tables() -> Tuple[Dict[str, str], List[str]]:
        descriptions = scoped_catalog(state.get("table_descriptions") or {})
        if preselected:
            return descriptions, preselected
        if not descriptions:
            try:
                from agent.db_utils.table_description_db_utils import list_table_description_from_db
                result = await list_table_description_from_db(user_id, agent_id, db_id=db_id)
                if not isinstance(result, dict):
                    raise TableAccessPolicyError("Table description response is not verified")
                record = result.get("record")
                if (result.get("status") is not True
                        or getattr(record, "chatbot_id", None) != agent_id
                        or getattr(record, "db_id", None) != db_id):
                    raise TableAccessPolicyError("Table description identity is not verified")
                raw = getattr(record, "description", None)
                parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
                if isinstance(parsed, list):
                    parsed = {name: value for item in parsed if isinstance(item, dict)
                              for name, value in item.items()}
                descriptions = scoped_catalog(parsed or {})
            except TableAccessPolicyError:
                raise
            except Exception as error:
                logger.warning("Table descriptions unavailable (%s); using verified catalog", type(error).__name__)
        if not descriptions:
            # The verified policy already enumerates the catalog. Never replace
            # it with all source tables when descriptions/introspection are absent.
            return {}, list(permitted)
        try:
            conf = await get_agent_node_config(agent_id, "select_table") if agent_id else None
            # The table-selection model call gets its own entry in the run's metrics.
            with measure_node_calls(state, "select_table", "select_table", conf):
                _, selected = await select_tables(
                    refined_query, json.dumps([{key: value} for key, value in descriptions.items()]),
                    node_conf=conf)
            return descriptions, selected
        except (TableAccessPolicyError, ModelConfigurationError):
            raise
        except Exception as error:
            logger.warning("Table selection unavailable (%s); using verified catalog", type(error).__name__)
            return descriptions, list(descriptions)

    async def get_few_shots():
        if state.get("few_shot_examples"):
            return state.get("few_shot_examples")
        
        if refined_query and agent_id:
            try:
                fs_service = await get_few_shot_service()
                fs_examples = await fs_service.get_similar_examples(
                    refined_query,
                    user_id,
                    agent_id,
                    3,
                    owner_id=owner_id,
                    session_id=session_id,
                    request_id=request_id,
                    db_id=db_id,
                )
                if fs_examples:
                    formatted = [{ex["question"]: ex["sql_query"]} for ex in fs_examples]
                    fs_str = build_few_shot_examples_string(json.dumps(formatted))
                    logger.info(f"[select_and_fewshots] Found {len(formatted)} few-shot examples")
                    return fs_str
            except ModelConfigurationError:
                raise
            except Exception as e:
                logger.warning(f"[select_and_fewshots] Few-shot retrieval skipped: {e}")
        return None

    # Validate the complete selection before starting few-shot retrieval, too.
    try:
        table_desc_dict, selected_tables = await get_tables()
        if not isinstance(selected_tables, list) or not selected_tables:
            raise TableAccessPolicyError("Selected table identity is invalid")
        blocked = blocked_table_names(selected_tables, permitted, excluded)
        if blocked:
            return deny_table_access(state, tables=blocked)
    except TableAccessPolicyError:
        return deny_table_access(state, policy_error=True)

    few_shot_examples = await get_few_shots()

    state.update(
        selected_tables=selected_tables,
        few_shot_examples=few_shot_examples,
        table_descriptions=table_desc_dict,
    )
    logger.info(
        "[WF] step.end=select_and_fewshots | request_id=%s | session_id=%s | n_tables=%d | has_fewshots=%s",
        state.get("request_id"),
        state.get("session_id"),
        len(selected_tables or []),
        bool(few_shot_examples),
    )

    return state


# ── helpers ──────────────────────────────────────────────────────────────────

def _dict_to_desc_str(d: Dict[str, str]) -> str:
    """Convert a {table: description} dict to the canonical line format."""
    lines = [f"Table Name: {k}, Table Description: {v}" for k, v in d.items()]
    return "\n".join(lines)
