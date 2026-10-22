from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import sys
from pathlib import Path

# Ensure agent root is on sys.path when running from scripts/
AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from agent.state import AgentState
from agent.nodes.refine import node_refine
from agent.nodes.select_table_and_fewshots import node_select_and_fewshots
from agent.nodes.sql_gen import node_sql_gen
from agent.nodes.sql_exec import node_sql_exec
from agent.nodes.final_answer import node_final_answer
from agent.nodes.graph_json import node_graph_json


def _truncate(value: Any, max_len: int = 120) -> Any:
    try:
        s = json.dumps(value, default=str)
    except Exception:
        try:
            s = str(value)
        except Exception:
            return value
    if len(s) <= max_len:
        return value
    return s[: max_len - 3] + "..."


def _print_state_delta(before: AgentState, after: AgentState, title: str) -> None:
    before = dict(before)
    after = dict(after)
    added = [k for k in after.keys() if k not in before]
    removed = [k for k in before.keys() if k not in after]
    changed = [k for k in after.keys() if k in before and before.get(k) != after.get(k)]
    print(f"\n=== {title} ===")
    if added:
        print("added:", added)
    if removed:
        print("removed:", removed)
    # Always show contents for key outputs we care about
    keys_to_show: List[str] = [
        "selected_tables",
        "sql_query",
        "sql_error",
        "db_result",
        "response",
        "graph_json",
    ]
    for k in changed:
        print(f"{k}:", _truncate(after.get(k)))
    for k in added:
        if k in keys_to_show:
            print(f"{k}:", _truncate(after.get(k)))


def build_initial_state(
    query: str,
    supported_graph_types: Optional[str],
    table_descriptions: Optional[Dict[str, str]],
    runtime_db_details: Optional[Dict[str, Any]],
    selected_tables: Optional[List[str]] = None,
    few_shot_examples: Optional[str] = None,
) -> AgentState:
    state: AgentState = {
        "query": query,
        "past_messages": [],
        "supported_graph_types": supported_graph_types,
        "table_descriptions": table_descriptions or {},
        "runtime_db_details": runtime_db_details,
    }
    if selected_tables:
        state["selected_tables"] = selected_tables
    if few_shot_examples:
        state["few_shot_examples"] = few_shot_examples
    return state


def run_each_node_live(state: AgentState) -> AgentState:
    # 1) refine
    before = deepcopy(state)
    state = node_refine(state)
    _print_state_delta(before, state, "refine")

    # 2) select tables + fewshots (respects preselected tables)
    before = deepcopy(state)
    state = node_select_and_fewshots(state)
    _print_state_delta(before, state, "select_and_fewshots")

    # 3) sql_gen (uses live DB for table_info if runtime_db_details and selected_tables provided)
    before = deepcopy(state)
    state = node_sql_gen(state)
    _print_state_delta(before, state, "sql_gen")

    # 4) sql_exec (executes against live DB)
    before = deepcopy(state)
    state = node_sql_exec(state)
    _print_state_delta(before, state, "sql_exec")

    # 5) final_answer (turns rows into natural language)
    before = deepcopy(state)
    state = node_final_answer(state)
    _print_state_delta(before, state, "final_answer")

    # 6) graph_json (post-processing suggestion + data)
    before = deepcopy(state)
    state = node_graph_json(state)
    _print_state_delta(before, state, "graph_json")

    return state


def run_full_flow_live(state: AgentState) -> AgentState:
    # Avoid persisting a separate registry: define the minimal flow inline
    from langgraph.graph import START, END, StateGraph

    graph = StateGraph(AgentState)
    graph.add_node("refine", node_refine)
    graph.add_node("select_and_fewshots", node_select_and_fewshots)
    graph.add_node("sql_gen", node_sql_gen)
    graph.add_node("sql_exec", node_sql_exec)
    graph.add_node("final_answer_node", node_final_answer)
    graph.add_node("graph_json_node", node_graph_json)

    graph.add_edge(START, "refine")
    graph.add_edge("refine", "select_and_fewshots")
    graph.add_edge("select_and_fewshots", "sql_gen")
    graph.add_edge("sql_gen", "sql_exec")
    graph.add_edge("sql_exec", "final_answer_node")
    graph.add_edge("final_answer_node", "graph_json_node")
    graph.add_edge("graph_json_node", END)

    app = graph.compile()
    return app.invoke(state)


def main() -> None:
    load_dotenv(override=True)

    parser = argparse.ArgumentParser("Test agent nodes against live data")
    parser.add_argument("--query", required=True)
    # DB connection (live data source)
    parser.add_argument("--db_engine", default=os.getenv("DB_ENGINE", "mysql"))
    parser.add_argument("--db_host", default=os.getenv("DB_HOST"))
    parser.add_argument("--db_port", default=os.getenv("DB_PORT"))
    parser.add_argument("--db_name", default=os.getenv("DB_NAME"))
    parser.add_argument("--db_user", default=os.getenv("DB_USER"))
    parser.add_argument("--db_password", default=os.getenv("DB_PASSWORD"))
    # Graph config
    parser.add_argument("--supported_graphs", default=os.getenv("SUPPORTED_GRAPHS", "Bar, Pie, Line, Histogram, Bubble"))
    # Tables
    parser.add_argument("--selected_tables", default=None, help="Comma-separated table names to include")
    parser.add_argument("--table_desc_json", default=None, help="Inline JSON or @path/to/file.json for table descriptions: {table: description}")
    # Few-shots
    parser.add_argument("--few_shots", default=None)
    # Mode
    parser.add_argument("--mode", choices=["nodes", "flow", "both"], default="both")

    args = parser.parse_args()

    # Parse table descriptions
    table_desc: Dict[str, str] = {}
    if args.table_desc_json:
        src = args.table_desc_json
        try:
            if src.startswith("@") and os.path.exists(src[1:]):
                with open(src[1:], "r", encoding="utf-8") as f:
                    table_desc = json.load(f)
            else:
                table_desc = json.loads(src)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: failed to parse table_desc_json: {e}. Proceeding with empty descriptions.")
            table_desc = {}

    selected_tables: Optional[List[str]] = None
    if args.selected_tables:
        selected_tables = [t.strip() for t in args.selected_tables.split(",") if t.strip()]

    runtime_db = {
        "db_engine": args.db_engine,
        "db_host": args.db_host,
        "db_port": args.db_port,
        "db_name": args.db_name,
        "db_user": args.db_user,
        "db_password": args.db_password,
    }

    init_state = build_initial_state(
        query=args.query,
        supported_graph_types=args.supported_graphs,
        table_descriptions=table_desc,
        runtime_db_details=runtime_db,
        selected_tables=selected_tables,
        few_shot_examples=args.few_shots,
    )

    final_state: AgentState = init_state

    if args.mode in ("nodes", "both"):
        print("\n############################")
        print("# Running each node (live) #")
        print("############################\n")
        final_state = run_each_node_live(deepcopy(init_state))

    if args.mode in ("flow", "both"):
        print("\n############################")
        print("# Running full flow (live)  #")
        print("############################\n")
        flow_state = run_full_flow_live(deepcopy(init_state))
        # Print concise flow summary
        keys = [
            "refined_query",
            "post_processing_query",
            "graph_suggestion",
            "selected_tables",
            "sql_query",
            "sql_error",
            "db_result",
            "response",
            "graph_json",
        ]
        summary = {k: flow_state.get(k) for k in keys if k in flow_state}
        print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()