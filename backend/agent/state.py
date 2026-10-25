from typing import TypedDict, List, Dict, Any, Optional, Tuple


class AgentState(TypedDict, total=False):
    # inputs
    query: str
    past_messages: List[Dict[str, Any]]
    few_shot_examples: Optional[str]
    table_descriptions: Optional[Dict[str, str]]
    selected_tables: Optional[List[str]]
    allowed_graphs: Optional[List[str]]
    include_graph_output: Optional[bool]  # Whether to generate graph visualization
    # runtime-only (must be present in state type for langgraph to carry it through)
    runtime_db_details: Optional[Dict[str, Any]]
    # multi-DB: db selected by db_router for this query, and the candidate list
    db_id: Optional[str]
    available_databases: Optional[List[Dict[str, Any]]]
    # cross-DB (multi-db-spec.md §11): set by db_router when a question needs >1 DB.
    # cross_db flips the graph onto the decompose→fan-out→merge branch.
    cross_db: Optional[bool]
    selected_dbs: Optional[List[Dict[str, Any]]]   # full connection dicts for the chosen DBs
    cross_db_plan: Optional[Dict[str, Any]]        # {sub_questions:[{db_id,question,key_column}], how}
    cross_db_results: Optional[List[Dict[str, Any]]]  # per-DB {db_id, columns, rows, sql_query, error}
    cross_db_combine: Optional[Dict[str, Any]]  # set by merge: {mode: "join"|"stack", on: column|None}
    user_id: Optional[str]
    owner_id: Optional[str]
    agent_id: Optional[str]
    session_id: Optional[str]  # Session identifier for usage tracking
    request_id: Optional[str]  # Request identifier for usage tracking 

    # derived
    action: Optional[str]  # Router decision: "END" or "sql_gen_node"
    refined_query: Optional[str]
    visualization_query: Optional[str]  # Replaces post_processing_query
    graph_suggestion: Optional[str]
    response: Optional[str]  # Final response (from router when action=END, or from final_answer_node)
    is_answered: Optional[bool]  # Whether the user's question was actually answered (set by final_answer_node)
    sql_query: Optional[str]
    db_result: Optional[List[Tuple]]
    graph_json: Optional[Dict[str, Any]]
    sql_error: Optional[str]
    answerability_error: Optional[str]  # Available schema cannot represent the requested metric.
    db_columns: Optional[List[str]]
    # Set by sql_exec when the generated query would have read a table switched off in
    # Tables & visibility. The query is not run and its SQL/rows are cleared, so this is
    # the only remaining trace — final_answer reads it to say access was denied rather
    # than reporting the empty result as "no rows found".
    access_denied_tables: Optional[List[str]]
    access_policy_error: Optional[bool]  # Required table policy unavailable/invalid; no source read.
    pandas_execution_result: Optional[str]
    pandas_plan: Optional[Dict[str, Any]]
    total_tokens: Optional[int]  # Accumulated token count across LLM calls
    follow_up_questions: Optional[List[str]]
    retry_count: Optional[int]  # Number of SQL generation retries attempted
    # Agent Health analytics: per-node spend collected by agent.utils.node_metrics
    # (one entry per node — provider, model, tokens, latency, calls, errors) and the
    # time spent inside the customer database. Both must be declared here or langgraph
    # drops them between nodes.
    node_events: Optional[List[Dict[str, Any]]]
    sql_exec_ms: Optional[int]

