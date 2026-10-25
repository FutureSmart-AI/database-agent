from typing import Any, Dict
from agent.state import AgentState
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.node_metrics import record_node_seconds
from otel_tracing import track_time
from logger import logger
import tempfile
import csv
from chart_agent.graph import graph_agent_graph
from agent.utils.model_config_loader import load_model_config
from agent.utils.model_profiles import ModelConfigurationError
import json
import os
import time
from agent.utils.prompts import _get_default_additional_instruction
from langchain_core.runnables import RunnableConfig

def agentstate_to_graphagentstate(parent_state: AgentState, csv_path: str) -> Dict[str, Any]:
    allowed_graphs = parent_state.get("allowed_graphs", None)
    try:
        if allowed_graphs:
            from chart_agent.models.graph_pydantic_models import ChartType
            if isinstance(allowed_graphs, str):
                allowed_graphs_list = [x.strip() for x in allowed_graphs.split(",") if x.strip()]
            else:
                allowed_graphs_list = list(allowed_graphs)
            allowed_graph_types = [ChartType(x) for x in allowed_graphs_list]
        else:
            allowed_graph_types = None
    except Exception:
        allowed_graph_types = None

    state: Dict[str, Any] = {
        "messages": [],
        "csv_path": csv_path,
        # Pass the user's ORIGINAL query so the chart_agent's router can detect
        # real chart intent from the user's actual words. visualization_query
        # is unreliable as a chart-intent signal because the upstream router
        # tends to hallucinate one even for plain data requests like "Show X".
        # The chart_agent already inspects data shape + query language together,
        # so giving it the raw query is the right input.
        "question": (
            parent_state.get("query")
            or parent_state.get("refined_query")
            or parent_state.get("question")
            or parent_state.get("visualization_query")
            or ""
        ),
        "allowed_graphs": allowed_graph_types,  # Native to subgraph
        "processed_dataframe": None,
        "suggested_chart_type": None,
        "graph_mapping_spec": None,
        "graph_data": None,
        "error": None,
        "needs_data_processing": None,
        "routing_reasoning": None,
        "direct_response": None,
        # Usage tracking identifiers (optional)
        "owner_id": parent_state.get("owner_id"),
        "agent_id": parent_state.get("agent_id"),
        "session_id": parent_state.get("session_id"),
        "request_id": parent_state.get("request_id"),
    }

    # These optional overrides may be populated later in graph_agent_node,
    # but we include the keys here for completeness.
    state["chart_agent_model"] = None
    state["chart_agent_provider"] = None
    state["chart_agent_prompt"] = None

    return state

def chart_follow_up_question(parent_state: AgentState, previous_had_chart: bool):
    """The chart request to hand the chart agent for a follow-up that narrows a charted answer.

    The chart agent is given the user's own words (see agentstate_to_graphagentstate), so
    "Only show the top two." after "Show a bar chart of the top five customers" reached it with
    no chart language and the chart was dropped. When the previous answer in this conversation
    did draw a chart (a recorded fact) and the router judged that this follow-up still wants one
    (a non-empty visualization_query, its "Chart inheritance" rule), the router's resolved chart
    request is used instead. Any other turn keeps the user's words, as before.
    """
    from agent.runner import _CHART_KEYWORDS

    query = (parent_state.get("query") or "").lower()
    resolved = (parent_state.get("visualization_query") or "").strip()
    if (previous_had_chart and resolved and parent_state.get("past_messages")
            and not any(k in query for k in _CHART_KEYWORDS)):
        return resolved
    return None


async def previous_answer_had_chart(session_id) -> bool:
    """Whether the latest logged answer in this conversation drew a chart. The current turn is
    logged after it is answered, so the latest row is the previous turn."""
    if not session_id:
        return False
    try:
        from sqlmodel import select
        from agent.services.sqlmodel_session import async_session
        from models.sql_models import ChatLogs

        async with async_session() as session:
            row = (await session.execute(
                select(ChatLogs.graph_output, ChatLogs.chart_output)
                .where(ChatLogs.session_id == session_id)
                .order_by(ChatLogs.created_at.desc()).limit(1))).first()
        return bool(row and (row[0] or row[1]))
    except Exception as e:
        logger.warning(f"[graph_agent] previous chart lookup failed: {e}")
        return False


@track_time("Node: Graph Agent Bridge")
async def graph_agent_node(parent_state: AgentState) -> AgentState:
    db_results = parent_state.get("db_result") or []
    db_columns = parent_state.get("db_columns") or []

    def _to_jsonable(value):
        import datetime
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        if isinstance(value, (int, float, str, type(None))):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return value.hex()
        if isinstance(value, (tuple, set, list)):
            return [_to_jsonable(v) for v in list(value)]
        if isinstance(value, dict):
            return {k: _to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        return str(value)
    if isinstance(db_results, (list, tuple)) and db_results and all(isinstance(r, dict) for r in db_results):
        header = list({k for d in db_results for k in d.keys()})
        rows = [[_to_jsonable(r.get(col)) for col in header] for r in db_results]
    elif isinstance(db_results, (list, tuple)) and db_results and all(isinstance(r, (list, tuple)) for r in db_results):
        if db_columns:
            header = [str(c) for c in db_columns]
        else:
            header = [f"col_{i}" for i in range(len(db_results[0]))]
        rows = [[_to_jsonable(v) for v in r] for r in db_results]
    elif isinstance(db_results, str):
        header, rows = ["value"], [[db_results]]
    else:
        header, rows = ["value"], [[_to_jsonable(db_results)]]

    with tempfile.NamedTemporaryFile(delete=False, mode="w", newline='', suffix=".csv") as tf:
        import csv
        writer = csv.writer(tf)
        writer.writerow(header)
        writer.writerows(rows)
        csv_path = tf.name

    from chart_agent.graph import graph_agent_graph
    subgraph_state = agentstate_to_graphagentstate(parent_state, csv_path)
    inherited = chart_follow_up_question(
        parent_state, await previous_answer_had_chart(parent_state.get("session_id")))
    if inherited:
        logger.info("[graph_agent] follow-up keeps the previous chart | question=%s", inherited[:200])
        subgraph_state["question"] = inherited

    # ----------------------------------------------------------------------
    # Inject chart_agent node configuration overrides (model + prompt)
    # so that both the chart router node and the graph mapping node
    # in the chart_agent workflow can use the same configuration that
    # is stored for the chart_agent node in the main nl2sql agent.
    # If no config is found for this agent_id, defaults will be used.
    # ----------------------------------------------------------------------
    agent_id = parent_state.get("agent_id")
    if agent_id:
        try:
            # Load model/provider/temperature using the shared helper
            from agent.utils.agent_config_loader import get_agent_node_config
            node_conf = await get_agent_node_config(agent_id, "chart_agent")
            if node_conf:
                subgraph_state["chart_agent_config"] = node_conf
                subgraph_state["chart_agent_model"] = node_conf["model"]
                subgraph_state["chart_agent_provider"] = node_conf["provider"]

            # Load prompt directly from ChatbotNodeConfig (not exposed by helper)
            try:
                from models.sql_models import ChatbotNodeConfig
                from agent.services.sqlmodel_session import get_async_session
                from sqlmodel import select

                async for session in get_async_session():
                    result = await session.execute(
                        select(ChatbotNodeConfig).where(
                            ChatbotNodeConfig.agent_id == agent_id,
                            ChatbotNodeConfig.node_name == "chart_agent",
                            ChatbotNodeConfig.deleted_at.is_(None),  # a node reset to default keeps its row
                        )
                    )
                    node_db = result.scalar_one_or_none()
                    if node_db and node_db.prompt:
                        subgraph_state["chart_agent_prompt"] = node_db.prompt
                        logger.info(f"✅ Loaded chart_agent prompt from node config (length: {len(node_db.prompt)})")
                    else:
                        logger.info(f"ℹ️ No chart_agent prompt config found for agent_id={agent_id}, will use defaults")
                    break
            except Exception as e:
                logger.warning(
                    f"graph_agent_node: failed to load chart_agent prompt from DB for agent_id={agent_id}: {e}"
                )
        except ModelConfigurationError:
            raise
        except Exception as e:
            logger.warning(
                f"graph_agent_node: failed to load chart_agent node config for agent_id={agent_id}: {e}. Will use defaults."
            )
    else:
        logger.info("ℹ️ No agent_id provided, chart_agent will use default config")
    
    if not subgraph_state.get("chart_agent_prompt"):
        try:
            default_prompt = _get_default_additional_instruction("chart_agent")
            if default_prompt:
                subgraph_state["chart_agent_prompt"] = default_prompt
                logger.info(f"✅ Using default chart_agent prompt (length: {len(default_prompt)})")
            else:
                logger.info("ℹ️ No default chart_agent prompt found in NODE_CONFIG_MAP")
        except Exception as e:
            logger.warning(f"graph_agent_node: failed to resolve default chart_agent prompt: {e}")
    
    start_time = time.time()
    config = RunnableConfig(
        tags=["chart_agent"],
        metadata={"owner_id": parent_state.get("owner_id"), "agent_id": parent_state.get("agent_id")}
    )
    subgraph_result = await graph_agent_graph.ainvoke(subgraph_state, config=config)
    execution_time = time.time() - start_time
    token_metrics = subgraph_result.get("token_metrics") or {}
    input_tokens = int(token_metrics.get("input_tokens", 0))
    output_tokens = int(token_metrics.get("output_tokens", 0))
    total_tokens = int(token_metrics.get("total_tokens", 0))

    try:
        os.remove(csv_path)
    except Exception:
        pass

    def recursive_to_dict(obj):
        if hasattr(obj, "model_dump"):
            return {k: recursive_to_dict(v) for k, v in obj.model_dump().items()}
        if hasattr(obj, "dict"):
            return {k: recursive_to_dict(v) for k, v in obj.dict().items()}
        if isinstance(obj, dict):
            return {k: recursive_to_dict(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [recursive_to_dict(v) for v in obj]
        return obj

    parent_state = dict(parent_state)
    graph_suggestion = recursive_to_dict(subgraph_result.get("suggested_chart_type"))
    graph_data = recursive_to_dict(subgraph_result.get("graph_data"))
    
    parent_state["graph_json"] = {
        "graph_suggestion": graph_suggestion,
        "graph_data": graph_data,
    }
    
    try:
        tracker = get_usage_tracker()
        chart_type = graph_suggestion if isinstance(graph_suggestion, str) else None
        duration_ms = float(execution_time * 1000.0)

        try:
            cfg = load_model_config()
        except Exception as e:
            logger.warning(f"Could not load model_config.json for graph_agent_bridge usage tracking: {e}")
            cfg = {}

        chart_conf = cfg.get("chart_agent", {}).get("suggest", {})
        provider = subgraph_state.get("chart_agent_provider") or chart_conf.get("provider")
        model_name = subgraph_state.get("chart_agent_model") or chart_conf.get("model")
        temperature = chart_conf.get("temperature", 0.0)

        # Determine key_type based on credential source. Resolved before the metric record
        # below so both the health event and the usage event report the same credential
        # owner for this node.
        try:
            from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model
            prov_for_key = provider or get_provider_from_model(model_name or "")
            _, key_type = await get_owner_api_key_for_provider(parent_state.get("owner_id"), prov_for_key, return_source=True)
            key_type = key_type or "platform-key"
        except Exception:
            key_type = "platform-key"

        # Same numbers, kept locally for the health event. Recorded on the COPY of the
        # parent state that this node returns — the original is no longer the one that
        # propagates.
        record_node_seconds(
            parent_state, "graph_agent", execution_time, provider=provider, model=model_name,
            input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
            key_type=key_type,
        )

        metadata = {
            "provider": provider,
            "model": model_name,
            "temperature": temperature,
        }
        usage_payload = {
            "owner_id": parent_state.get("owner_id"),
            "service_id": parent_state.get("agent_id"),
            "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
            "operation": "llm_call",
            "label": "chart_generation",
            "session_id": parent_state.get("session_id"),
            "request_id": parent_state.get("request_id"),
            "operation_id": "graph_agent",
            "metadata": metadata,
            "metrics": [
                {"name": "input_tokens", "value": float(input_tokens or 0)},
                {"name": "output_tokens", "value": float(output_tokens or 0)},
                {"name": "total_tokens", "value": float(total_tokens or 0)},
                {"name": "duration_ms", "value": duration_ms},
            ],
        }
        logger.info(f"Usage (local) graph_agent payload={json.dumps(usage_payload)}")
        await tracker.record_event(
            owner_id=parent_state.get("owner_id"),
            agent_id=parent_state.get("agent_id"),
            operation="llm_call",
            label="chart_generation",
            session_id=parent_state.get("session_id"),
            request_id=parent_state.get("request_id"),
            operation_id="graph_agent",
            key_type=key_type,
            metadata={k: v for k, v in metadata.items() if k != "key_type"},
            metrics=[
                {"name": "input_tokens", "value": float(input_tokens or 0)},
                {"name": "output_tokens", "value": float(output_tokens or 0)},
                {"name": "total_tokens", "value": float(total_tokens or 0)},
                {"name": "duration_ms", "value": duration_ms},
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to record graph_agent usage event (non-blocking): {e}")
    
    return parent_state
