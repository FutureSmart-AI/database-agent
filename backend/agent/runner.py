from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
# load_dotenv(override=True)
import os
from langgraph.graph import StateGraph, START, END

from agent.state import AgentState
from agent.nodes.router import node_router
from agent.nodes.db_router import node_db_router
from agent.nodes.cross_db_fanout import node_cross_db_fanout
from agent.nodes.cross_db_merge import node_cross_db_merge
from agent.nodes.select_table_and_fewshots import node_select_and_fewshots
from agent.nodes.sql_gen import node_sql_gen
from agent.nodes.sql_exec import node_sql_exec
from agent.nodes.final_answer import node_final_answer
from agent.nodes.graph_agent_bridge import graph_agent_node
from logger import logger

from agent.nodes.invoke_pandas import invoke_pandas_agent_node
from agent.nodes.check_pandas import check_pandas_needed
from langsmith import traceable
from langchain_core.runnables import RunnableConfig
from otel_tracing import track_time

def route_after_router(state: AgentState) -> str:
    """Route based on router decision."""
    action = state.get("action", "sql_gen_node")
    return action


def route_after_db_router(state: AgentState) -> str:
    """Cross-DB questions (>=2 DBs selected) take the decompose→fan-out→merge branch;
    everything else keeps the single-DB path unchanged."""
    return "cross_db" if state.get("cross_db") else "single"


async def route_after_merge(state: AgentState) -> str:
    """After the cross-DB join: surface a merge failure, else decide pandas like the SQL path."""
    if state.get("sql_error"):
        return "final_answer_node"
    return await check_pandas_needed(state)

_CHART_KEYWORDS = ("chart", "graph", "plot", "pie", "histogram", "visuali", "diagram")


def route_after_final_answer(state: AgentState) -> str:
    """Route after final_answer_node: generate graph if requested, otherwise END."""
    if state.get("answerability_error") or state.get("access_denied_tables") or state.get("access_policy_error") or state.get("sql_error"):
        return "END"
    include_graph = state.get("include_graph_output", False)
    if not include_graph:
        return "END"
    # Skip the chart subgraph when there is clearly NO chart intent: the router judged the query
    # non-visual (empty visualization_query) AND the raw query has no chart language. Saves the
    # chart agent's LLM round-trip(s) on plain data questions sent with chart_output=true.
    # Any chart signal at all → run the chart agent as before (empty allowed_charts means
    # UNRESTRICTED chart types, not disabled — see graph_agent_bridge.py).
    viz_query = (state.get("visualization_query") or "").strip()
    raw_query = (state.get("query") or "").lower()
    if not viz_query and not any(k in raw_query for k in _CHART_KEYWORDS):
        logger.info(
            "[WF] graph_agent skipped: no chart intent (empty visualization_query, no chart keywords) | request_id=%s",
            state.get("request_id"),
        )
        return "END"
    return "graph_agent"

async def route_after_sql_exec(state: AgentState) -> str:
    """Route after sql_exec.

    - No error  → await check_pandas_needed to proceed normally.
    - Error, retries remaining → back to sql_gen with error context injected.
    - Error, max retries reached → final_answer_node (let it surface the error).
    """
    MAX_RETRIES = int(os.getenv("SQL_MAX_RETRIES", "2"))
    if state.get("sql_error"):
        retry_count = state.get("retry_count", 0)
        if retry_count < MAX_RETRIES:
            return "sql_gen"
        logger.warning(
            "[WF] sql_exec max retries reached | retry_count=%d | request_id=%s",
            retry_count,
            state.get("request_id"),
        )
        return "final_answer_node"
    return await check_pandas_needed(state)

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("router", node_router)
    graph.add_node("db_router", node_db_router)
    graph.add_node("cross_db_fanout", node_cross_db_fanout)
    graph.add_node("cross_db_merge", node_cross_db_merge)
    graph.add_node("select_and_fewshots", node_select_and_fewshots)
    graph.add_node("sql_gen", node_sql_gen)
    graph.add_node("sql_exec", node_sql_exec)
    graph.add_node("invoke_pandas", invoke_pandas_agent_node)
    graph.add_node("final_answer_node", node_final_answer)
    graph.add_node("graph_agent", graph_agent_node)

    graph.add_edge(START, "router")

    # Conditional routing after router node: multi-DB selection happens in db_router,
    # which then hands off to table/few-shot selection.
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {
            "END": END,
            "sql_gen_node": "db_router"
        }
    )

    # After db_router: cross-DB questions branch to fan-out → merge. The per-DB sub-questions
    # (the plan) are produced by db_router itself in the same LLM call that selected the DBs —
    # there is no separate planner step.
    graph.add_conditional_edges(
        "db_router",
        route_after_db_router,
        {
            "cross_db": "cross_db_fanout",
            "single": "select_and_fewshots",
        }
    )

    # Cross-DB branch: run each sub-question per-DB → join results in pandas.
    graph.add_edge("cross_db_fanout", "cross_db_merge")
    graph.add_conditional_edges(
        "cross_db_merge",
        route_after_merge,
        {
            "invoke_pandas": "invoke_pandas",
            "final_answer_node": "final_answer_node",
        }
    )

    graph.add_edge("select_and_fewshots", "sql_gen")
    graph.add_edge("sql_gen", "sql_exec")

    # After sql_exec: retry sql_gen on error, proceed on success
    graph.add_conditional_edges(
        "sql_exec",
        route_after_sql_exec,
        {
            "sql_gen": "sql_gen",
            "invoke_pandas": "invoke_pandas",
            "final_answer_node": "final_answer_node",
        }
    )

    graph.add_edge("invoke_pandas", "final_answer_node")

    # Conditional routing after final_answer_node: generate graph if requested
    graph.add_conditional_edges(
        "final_answer_node",
        route_after_final_answer,
        {
            "graph_agent": "graph_agent",
            "END": END
        }
    )

    graph.add_edge("graph_agent", END)

    return graph.compile()


app = build_graph()


@traceable(run_type="chain", name="NL2SQL LangGraph")
@track_time("NL2SQL: Full Flow")
async def run_agent_flow(
    query: str,
    past_messages: Optional[List[Dict[str, Any]]],
    table_descriptions: Optional[Dict[str, str]],
    runtime_db_details: Optional[Dict[str, Any]],
    selected_tables: Optional[List[str]] = None,
    few_shot_examples: Optional[str] = None,
    user_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    allowed_graphs: Optional[List[str]] = None,
    include_graph_output: bool = False,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    follow_up: bool = False,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    logger.info(
        "[WF] flow.start | request_id=%s | session_id=%s | agent_id=%s | has_runtime_db=%s",
        request_id,
        session_id,
        agent_id,
        bool(runtime_db_details),
    )
    # Stamp the identifiers on THIS traceable's root run, not just on the inner graph
    # invoke below: the Agent Health cost rollup filters LangSmith on root runs
    # (is_root=True), so metadata that only reaches the child span is invisible to it.
    try:
        from langsmith.run_helpers import get_current_run_tree
        _root = get_current_run_tree()
        if _root is not None and isinstance(getattr(_root, "extra", None), dict):
            _md = _root.extra.setdefault("metadata", {})
            for _k, _v in (("agent_id", agent_id), ("owner_id", owner_id), ("user_id", user_id),
                           ("chat_id", chat_id), ("session_id", session_id), ("request_id", request_id)):
                if _v:
                    _md[_k] = _v
    except Exception as _md_err:
        logger.debug("[WF] langsmith root metadata skipped: %s", _md_err)

    state: AgentState = {
        "query": query,
        "past_messages": past_messages or [],
        "table_descriptions": table_descriptions or {},
        # runtime-only injection for sql_exec
        "runtime_db_details": runtime_db_details,
    }
    if selected_tables:
        state["selected_tables"] = selected_tables
    if few_shot_examples:
        state["few_shot_examples"] = few_shot_examples
    if user_id:
        state["user_id"] = user_id
    if owner_id:
        state["owner_id"] = owner_id
    if agent_id:
        state["agent_id"] = agent_id
    if allowed_graphs:
        state["allowed_graphs"] = allowed_graphs
    if session_id:
        state["session_id"] = session_id
    if request_id:
        state["request_id"] = request_id
    state["include_graph_output"] = include_graph_output
    if not runtime_db_details:
        logger.info(
            "[WF] flow.path=router_only | request_id=%s | session_id=%s",
            request_id,
            session_id,
        )
        result = await node_router(state)
    else:
        logger.info(
            "[WF] flow.path=full_graph | request_id=%s | session_id=%s | order=router->select_and_fewshots->sql_gen->sql_exec->(retry_sql_gen?)"
            "->(invoke_pandas?)->final_answer_node->(graph_agent?)",
            request_id,
            session_id,
        )
        tags = ["nl2sql", "agent"]
        metadata: Dict[str, Any] = {}
        if user_id:
            tags.append(f"user_id:{user_id}")
            metadata["user_id"] = user_id
        if owner_id:
            tags.append(f"owner_id:{owner_id}")
            metadata["owner_id"] = owner_id
        if agent_id:
            tags.append(f"agent_id:{agent_id}")
            metadata["agent_id"] = agent_id
        if chat_id:
            # Stamped so the Agent Health cost backfill can match a LangSmith run back to
            # its health row (agent.utils.langsmith_cost.fetch_agent_costs keys on this).
            metadata["chat_id"] = chat_id
        if session_id:
            metadata["session_id"] = session_id
        config = RunnableConfig(
         tags=tags,
         metadata=metadata,
        )
        result = await app.ainvoke(state, config=config)
    logger.info(
        "[WF] flow.end | request_id=%s | session_id=%s | action=%s | has_sql=%s | has_error=%s",
        request_id,
        session_id,
        result.get("action"),
        bool(result.get("sql_query")),
        bool(result.get("sql_error") or result.get("error")),
    )

    # Capture the LangSmith trace reference for this run so the API can surface it in the
    # final response. Must run inside this @traceable scope to see the active run tree.
    # Whose credentials paid for this run, stamped on the root run so LangSmith can be
    # filtered by it. Added AFTER the graph, unlike the identifiers above: key_type is
    # decided per LLM call inside the nodes, so it does not exist yet at entry. "mixed"
    # is a real answer here — nodes on different providers can land on different sides.
    try:
        from agent.utils.agent_health_service import roll_up_key_type
        from agent.utils.node_metrics import get_node_events
        from langsmith.run_helpers import get_current_run_tree

        _key_type = roll_up_key_type(get_node_events(result))
        _root = get_current_run_tree()
        if _key_type and _root is not None and isinstance(getattr(_root, "extra", None), dict):
            _root.extra.setdefault("metadata", {})["key_type"] = _key_type
    except Exception as _kt_err:
        logger.debug("[WF] langsmith key_type metadata skipped: %s", _kt_err)

    try:
        from langsmith.run_helpers import get_current_run_tree
        run_tree = get_current_run_tree()
        if run_tree is not None:
            # trace_id identifies the whole trace; for a root run it equals the run id.
            _tid = getattr(run_tree, "trace_id", None) or getattr(run_tree, "id", None)
            result["trace_id"] = str(_tid) if _tid else None
            # The root run id specifically — what Agent Health prices against via
            # read_run, independent of the project name or any metadata filter.
            _rid = getattr(run_tree, "id", None)
            result["langsmith_run_id"] = str(_rid) if _rid else None
            try:
                result["langsmith_trace_url"] = run_tree.get_url()
            except Exception:
                result["langsmith_trace_url"] = None
            # Parent context for work the API layer runs AFTER this scope (follow-up
            # generation off the critical path): lets it attach to THIS trace instead of
            # appearing as a separate root run in LangSmith.
            try:
                result["_ls_parent_headers"] = run_tree.to_headers()
            except Exception:
                result["_ls_parent_headers"] = None
    except Exception as ls_err:
        logger.debug("[WF] langsmith trace capture skipped: %s", ls_err)

    # Generate follow-up questions inside this traceable scope so they appear
    # as a child span under "NL2SQL LangGraph" in LangSmith, not a separate trace.
    if follow_up:
        try:
            from agent.utils.follow_up import generate_follow_up_questions
            fu_questions = await generate_follow_up_questions(
                owner_id=owner_id,
                agent_id=agent_id,
                messages=past_messages or [],
                refined_query=result.get("refined_query", query),
                response=result.get("response", ""),
            )
            result["follow_up_questions"] = fu_questions
        except Exception as fu_err:
            logger.error("[WF] follow_up generation failed: %s", fu_err)
            result["follow_up_questions"] = None

    return result


