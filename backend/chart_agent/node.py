from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError

"""
Graph Agent as a LangGraph workflow.
Uses Pandas Agent as a subgraph to process CSV and generate graph data.
NEW: Uses graph_mapper (schema-only) + graph_assembler (pure Python) approach.
"""

from typing import TypedDict, Annotated, Sequence, List, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
try:
    from langchain_groq import ChatGroq
except Exception:
    ChatGroq = None

try:
    from langchain_anthropic import ChatAnthropic
except Exception:
    ChatAnthropic = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None

from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI

try:
    from groq import RateLimitError as GroqRateLimitError  # type: ignore
except Exception:  # pragma: no cover - groq SDK not installed
    GroqRateLimitError = Exception  # type: ignore[misc,assignment]

import pandas as pd
import io
import operator
import os
from pandas_agent.graph import pandas_agent_graph
from chart_agent.models.graph_pydantic_models import ChartType, GraphResponse, ChartTypeResponse, DataFrameStructure
from chart_agent.utils.prompt import SUGGEST_CHART_SYSTEM_PROMPT
from agent.utils.owner_credential_utils import get_llm_api_key
from chart_agent.utils.model_config_loader import load_model_config
from agent.utils.agent_config_loader import get_agent_node_config, merge_agent_config_with_defaults
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs
from pydantic import create_model
from enum import Enum
import json
from logger import logger
from chart_agent.utils.graph_mapper import extract_dataframe_schema, generate_graph_mapping
from chart_agent.utils.graph_assembler import (
    assemble_graph_data,
    combine_label_columns,
    infer_correct_chart_type,
    plotted_measure_columns,
)
from otel_tracing import track_time
from langsmith import traceable


# ============================================================================
# STATE DEFINITION
# ============================================================================
class GraphAgentState(TypedDict):
    """State for the Graph Agent workflow."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    csv_path: str
    question: str
    allowed_graphs: List[ChartType] | None
    owner_id: str | None
    agent_id: str | None  # Agent ID for loading agent-specific configuration

    # Optional overrides injected from the main NL2SQL agent
    # When the graph agent is called from the nl2sql flow, the agent layer
    # can set these to force a specific model/provider and/or additional instructions
    # for the chart_agent node. Standalone chart_agent usages can ignore them.
    chart_agent_config: Dict[str, Any] | None
    chart_agent_model: str | None
    chart_agent_provider: str | None
    chart_agent_prompt: str | None

    # Pandas agent outputs
    processed_dataframe: pd.DataFrame | None

    # Chart suggestion
    suggested_chart_type: ChartType | None

    # Graph mapping
    graph_mapping_spec: dict | None

    # Set once the chart type has been checked against the mapped measures
    chart_type_checked: bool | None

    # Final graph data
    graph_data: dict | None

    # Error handling
    error: str | None

    # Aggregated token metrics for internal LLM calls (router, pandas planning, etc.)
    token_metrics: Dict[str, Any] | None

    # Router outputs (new unified approach)
    action: str | None  # "END" or "invoke_pandas_agent"
    chart_type: str | None  # Suggested chart type as string
    refined_query: str | None  # Refined query with history resolved
    response: str | None  # Direct response when action=END

    # Usage tracking identifiers
    session_id: str | None
    request_id: str | None

# ============================================================================
# NODE FUNCTIONS
# ============================================================================

@track_time("Node: Invoke Pandas Agent")
async def invoke_pandas_agent(state: GraphAgentState) -> GraphAgentState:
    """Invoke the Pandas agent subgraph to process and transform data."""
    logger.info(f"Invoking Pandas agent - Question: {state['question'][:100]}")
    
    subgraph_input = {
        "messages": [HumanMessage(content=state["question"])],
        "csv_path": state["csv_path"],
        "query": state["question"],
        "chart_type": state.get("suggested_chart_type"),
        "owner_id": state.get("owner_id"),
        "agent_id": state.get("agent_id"),  # Pass agent_id for agent-specific config
        "plan": None,
        "execution_result": None,
        "error": None,
        "retry_count": 0  # Initialize retry counter
    }
    
    try:
        subgraph_result = await pandas_agent_graph.ainvoke(subgraph_input)
        logger.info("Pandas agent completed")
    except Exception as e:
        logger.error(f"Pandas agent failed: {str(e)}")
        return {
            **state,
            "error": f"Pandas agent error: {str(e)}",
            "messages": state["messages"] + [AIMessage(content=f"Error: {str(e)}")]
        }
    
    if subgraph_result.get("error"):
        logger.error(f"Pandas agent error: {subgraph_result['error'][:100]}")
        return {
            **state,
            "error": subgraph_result["error"],
            "messages": state["messages"] + [AIMessage(content=f"Error: {subgraph_result['error']}")]
        }
    
    execution_result = subgraph_result.get("execution_result")
    if not execution_result:
        logger.error("No execution result from Pandas agent")
        return {
            **state,
            "error": "No execution result from Pandas agent",
            "messages": state["messages"] + [AIMessage(content="Error: Could not parse DataFrame")]
        }
    
    processed_df = None
    
    # Try to extract CSV block first
    if "CSV_DATA_START" in execution_result:
        try:
            start = execution_result.index("CSV_DATA_START") + len("CSV_DATA_START")
            end = execution_result.index("CSV_DATA_END", start)
            csv_text = execution_result[start:end].strip()
            processed_df = pd.read_csv(io.StringIO(csv_text))
            logger.info(f"CSV extracted successfully. Shape: {processed_df.shape}")
        except Exception as e:
            logger.debug(f"CSV extraction failed: {str(e)}")
    
    # Fallback parsing
    if processed_df is None:
        logger.debug("Using fallback DataFrame parsing")
        df_blocks = execution_result.split("\n" + "="*70 + "\n")
        for block in df_blocks:
            if "DataFrame:" in block:
                data_start = block.find("Data:")
                if data_start != -1:
                    data_section = block[data_start + 5:].strip()
                    summary_start = data_section.find("Summary Statistics:")
                    if summary_start != -1:
                        data_section = data_section[:summary_start].strip()
                    try:
                        processed_df = pd.read_csv(io.StringIO(data_section))
                        break
                    except:
                        try:
                            processed_df = pd.read_csv(io.StringIO(data_section), sep=r'\s+', engine='python')
                            break
                        except:
                            continue
    
    if processed_df is None:
        logger.error("Could not extract DataFrame")
        return {
            **state,
            "error": "Could not extract processed DataFrame",
            "messages": state["messages"] + [AIMessage(content="Error: Could not parse DataFrame")]
        }
    
    # Merge pandas subgraph token metrics into graph-level token_metrics
    try:
        sub_token_metrics = subgraph_result.get("token_metrics") or {}
        if sub_token_metrics:
            merged_metrics: Dict[str, Any] = dict(state.get("token_metrics") or {})
            for k, v in sub_token_metrics.items():
                if isinstance(v, (int, float)):
                    merged_metrics[k] = float(merged_metrics.get(k, 0.0) + float(v))
            state = {**state, "token_metrics": merged_metrics}
    except Exception:
        # Metrics merging should never break the main flow
        pass

    logger.info(f"DataFrame processed: {processed_df.shape[0]} rows × {processed_df.shape[1]} cols")
    
    

    # Record usage event for pandas agent step
    try:
        from agent.utils.usage_tracking import get_usage_tracker
        import asyncio
        tracker = get_usage_tracker()
        owner_id = state.get("owner_id")
        sub_token_metrics = subgraph_result.get("token_metrics") or {}
        input_tokens = sub_token_metrics.get("input_tokens", 0)
        output_tokens = sub_token_metrics.get("output_tokens", 0)
        total_tokens = sub_token_metrics.get("total_tokens", 0)
        asyncio.create_task(tracker.record_llm_call(
            owner_id=owner_id,
            agent_id=None,
            operation="chart_pandas_agent",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            extra_metrics=[],
        ))
    except Exception:
        pass

    return {
        **state,
        "processed_dataframe": processed_df,
        "messages": state["messages"] + [AIMessage(content="DataFrame processed successfully")]
    }


@traceable(run_type="chain", name="chart_validation_check")
async def _trace_chart_validation(
    chart_type_in: str,
    data_shape: List[int],
    data_columns: List[str],
    numeric_columns: List[str],
    non_numeric_columns: List[str],
    allowed_graphs: List[str] | None,
    chart_type_out: str,
    corrected: bool,
    reason: str,
) -> Dict[str, Any]:
    """Pure tracing wrapper — all args are JSON-friendly so LangSmith captures
    them as the span input. The returned dict is captured as the span output.
    Must be ``async`` so the LangSmith parent-run context propagates from the
    surrounding async LangGraph node.
    """
    return {
        "chart_type_in": chart_type_in,
        "chart_type_out": chart_type_out,
        "corrected": corrected,
        "reason": reason,
        "data_shape": data_shape,
        "data_columns": data_columns,
        "numeric_columns": numeric_columns,
        "non_numeric_columns": non_numeric_columns,
        "allowed_graphs": allowed_graphs,
    }


@track_time("Node: Validate Chart Type")
async def validate_chart_type_node(state: GraphAgentState) -> GraphAgentState:
    """
    Structural validation node — runs AFTER pandas agent, BEFORE mapping.

    Inspects the actual DataFrame shape and corrects the chart type when the
    data structure is incompatible with what the router selected. This is a
    pure-Python, zero-LLM step that prevents silent data loss downstream
    (e.g. a Line Chart silently dropping a second currency series).

    All corrections are logged explicitly AND emitted as a `chart_validation_check`
    LangSmith span with full JSON input/output so the trace shows exactly what
    went in and what came out.
    """
    df = state.get("processed_dataframe")
    current_chart = state.get("suggested_chart_type")

    if state.get("chart_type_checked"):
        # Second pass after a correction re-mapped the corrected type.
        return state

    if df is None or current_chart is None:
        # Emit a trace span so the no-op case is also visible in LangSmith
        await _trace_chart_validation(
            chart_type_in=str(current_chart) if current_chart else None,
            data_shape=list(df.shape) if df is not None else [],
            data_columns=list(df.columns) if df is not None else [],
            numeric_columns=[],
            non_numeric_columns=[],
            allowed_graphs=None,
            chart_type_out=str(current_chart) if current_chart else None,
            corrected=False,
            reason="skipped: missing DataFrame or chart type",
        )
        return {**state, "chart_type_checked": True}

    # Normalise chart type to its string value
    chart_type_str = current_chart.value if hasattr(current_chart, "value") else str(current_chart)

    # Build allowed list as plain strings (for the validator)
    allowed_graphs = state.get("allowed_graphs")
    allowed_strs = [g.value for g in allowed_graphs] if allowed_graphs else None

    # The mapping model names the plotted measures and the label columns.
    mapping_spec = state.get("graph_mapping_spec") or {}
    measure_columns = mapping_spec.get("measure_columns")
    label_columns = mapping_spec.get("label_columns")

    # Pre-compute column-type summaries for the trace
    numeric_cols = plotted_measure_columns(df, measure_columns)
    non_numeric_cols = [c for c in df.columns if c not in numeric_cols]

    corrected_str, reason = infer_correct_chart_type(
        df, chart_type_str, allowed_strs, measure_columns, label_columns
    )

    if reason:
        logger.warning(f"⚠️  [CHART_VALIDATION] Chart type corrected | {reason}")
        logger.info(
            f"   Original: {chart_type_str} | Corrected: {corrected_str} | "
            f"DataFrame shape: {df.shape[0]} rows × {df.shape[1]} cols | "
            f"Columns: {list(df.columns)}"
        )
        try:
            corrected_enum = ChartType(corrected_str)
        except ValueError:
            logger.error(f"   Corrected chart type '{corrected_str}' is not a valid ChartType — keeping original")
            await _trace_chart_validation(
                chart_type_in=chart_type_str,
                data_shape=list(df.shape),
                data_columns=list(df.columns),
                numeric_columns=numeric_cols,
                non_numeric_columns=non_numeric_cols,
                allowed_graphs=allowed_strs,
                chart_type_out=chart_type_str,  # kept original
                corrected=False,
                reason=f"correction blocked: {corrected_str!r} is not a valid ChartType",
            )
            return {**state, "chart_type_checked": True}

        # Emit trace span showing the correction
        await _trace_chart_validation(
            chart_type_in=chart_type_str,
            data_shape=list(df.shape),
            data_columns=list(df.columns),
            numeric_columns=numeric_cols,
            non_numeric_columns=non_numeric_cols,
            allowed_graphs=allowed_strs,
            chart_type_out=corrected_str,
            corrected=True,
            reason=reason,
        )

        # Clear the mapping so the graph re-maps the corrected type once.
        return {
            **state,
            "suggested_chart_type": corrected_enum,
            "chart_type": corrected_str,
            "graph_mapping_spec": None,
            "chart_type_checked": True,
        }

    logger.info(
        f"✅ [CHART_VALIDATION] {chart_type_str} is structurally compatible with the data "
        f"({df.shape[0]} rows × {df.shape[1]} cols)"
    )

    # Emit trace span showing no-correction path
    await _trace_chart_validation(
        chart_type_in=chart_type_str,
        data_shape=list(df.shape),
        data_columns=list(df.columns),
        numeric_columns=numeric_cols,
        non_numeric_columns=non_numeric_cols,
        allowed_graphs=allowed_strs,
        chart_type_out=chart_type_str,
        corrected=False,
        reason="structurally compatible — no correction needed",
    )

    return {**state, "chart_type_checked": True}


async def suggest_chart_type_node(state: GraphAgentState) -> GraphAgentState:
    """Suggest the best chart type for the data."""
    logger.info("Suggesting chart type")
    allowed_graphs = state.get("allowed_graphs")
    
    # If only one chart type allowed, skip LLM
    if allowed_graphs and len(allowed_graphs) == 1:
        chart_type = allowed_graphs[0].value
        logger.info(f"Single allowed chart type: {chart_type}")
        return {
            **state,
            "suggested_chart_type": chart_type,
            "messages": state["messages"] + [AIMessage(content=f"Chart type: {chart_type}")]
        }
    
    # Prepare chart list
    if allowed_graphs:
        valid_chart_types = [chart_type.value for chart_type in allowed_graphs]
        chart_list = ", ".join(valid_chart_types)
    else:
        valid_chart_types = [ct.value for ct in ChartType]
        chart_list = ", ".join(valid_chart_types)
    
    system_prompt = SUGGEST_CHART_SYSTEM_PROMPT.replace("{chart_list}", chart_list)
    
    agent_id = state.get("agent_id")
    node_config = await get_agent_node_config(agent_id, "chart_agent")
    suggest_conf = operation_config("chart_agent.suggest", node_config)

    suggest_model = suggest_conf.get("model")
    suggest_provider = suggest_conf.get("provider")

    owner_id = state.get("owner_id")

    # Get API keys with logging
    logger.info(f"🤖 [LLM_CALL] Chart Suggest node | owner_id: {owner_id} | model: {suggest_model}")
    suggest_api_key = await get_llm_api_key(owner_id, suggest_model, suggest_provider) if suggest_model else None
    
    # Log which credential source is being used
    if suggest_api_key:
        logger.info(f"🚀 [LLM_CALL] Chart Suggest node initialized | owner_id: {owner_id} | model: {suggest_model}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] Chart Suggest node using default env credentials | owner_id: {owner_id} | model: {suggest_model}")

    # Dynamically select the model class based on provider
    provider_lower = suggest_provider.lower() if suggest_provider else "openai"

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
    elif provider_lower == "google" or provider_lower == "gemini":
        if ChatGoogleGenerativeAI is None:
            logger.error(f"ChatGoogleGenerativeAI not available but provider is {provider_lower}")
            return {**state, "error": f"ChatGoogleGenerativeAI not available for {provider_lower}"}
        ModelClass = ChatGoogleGenerativeAI
    else:
        ModelClass = ChatOpenAI

    ModelClass = configured_model_factory(suggest_conf)

    openai_kwargs = (
        structured_tool_chat_kwargs(suggest_model)
        if provider_lower in ("openai", "azure_openai")
        else {}
    )

    llm = ModelClass(model=suggest_model, api_key=suggest_api_key, **openai_kwargs) if suggest_api_key else ModelClass(model=suggest_model, **openai_kwargs) if suggest_model else None
    if not llm:
        logger.error("No model configured for chart suggestion")
        return {**state, "error": "No model configured"}
    
    # Create dynamic model if needed
    if allowed_graphs and len(allowed_graphs) > 1:
        enum_name = "DynamicChartType"
        DynamicChartType = Enum(enum_name, {v.replace(' ', '_').upper(): v for v in valid_chart_types})
        structured_model = create_model('DynamicChartTypeResponse', chart_type=(DynamicChartType, ...))
    else:
        structured_model = ChartTypeResponse
    
    if provider_lower == "groq":
        structured_llm = llm.with_structured_output(structured_model)
    elif provider_lower == "google":
        # Google GenAI doesn't support method="function_calling", use default structured output
        structured_llm = llm.with_structured_output(structured_model)
    else:
        # OpenAI and other providers: use function_calling method
        structured_llm = llm.with_structured_output(structured_model, method="function_calling")
    response = await structured_llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=state["question"]),
    ])
    
    suggestion = response.chart_type.value if hasattr(response.chart_type, 'value') else str(response.chart_type)
    logger.debug(f"LLM suggested: {suggestion}")
    
    # Validate against allowed types
    if suggestion not in valid_chart_types:
        logger.warning(f"Invalid suggestion '{suggestion}', using default")
        suggestion = valid_chart_types[0] if valid_chart_types else "Bar Chart"
    
    logger.info(f"Chart type: {suggestion}")
    return {
        **state,
        "suggested_chart_type": suggestion,
        "messages": state["messages"] + [AIMessage(content=f"Chart: {suggestion}")]
    }


@track_time("Node: Generate Graph Mapping")
async def generate_graph_mapping_node(state: GraphAgentState) -> GraphAgentState:
    """
    Generate graph field mappings using SCHEMA-ONLY approach.
    LLM sees ONLY column names and types, NOT actual data values.
    """
    logger.info("Generating field mappings (schema-only)")
    
    chart_type = state["suggested_chart_type"]
    if not chart_type:
        logger.error("No chart type suggested")
        return {**state, "error": "No chart type suggested"}
    
    df = state["processed_dataframe"]
    if df is None:
        logger.error("No DataFrame available")
        return {**state, "error": "No DataFrame available"}
    
    try:
        # Extract schema (columns and types only)
        logger.info("Extracting DataFrame schema")
        df_schema = extract_dataframe_schema(df)
        logger.debug(f"Schema: {list(df_schema['columns'].keys())}")
        
        # Generate mappings with LLM (1 call, schema-only)
        logger.info(f"Generating mappings for {chart_type}")
        mapping_conf = operation_config("chart_agent.mapping", state.get("chart_agent_config"))
        mapping_model = mapping_conf["model"]

        # Allow the calling agent to inject additional instructions for mapping
        # If not set, custom_instruction will be None and base prompt will be used
        custom_instruction = state.get("chart_agent_prompt")
        if custom_instruction:
            logger.info(f"✅ Using chart_agent prompt from node config (length: {len(custom_instruction)})")
        else:
            logger.info(f"ℹ️ No chart_agent prompt config, using base mapping prompt only")

        # Get provider from state (from nl2sql agent config) or infer from model
        override_provider = mapping_conf["provider"]

        mapping_spec = await generate_graph_mapping(
            df_schema=df_schema,
            user_query=state["question"],
            chart_type=chart_type,
            owner_id=state.get("owner_id"),
            model=mapping_model,
            provider=override_provider,
            temperature=0,
            verbose=True,
            custom_instruction=custom_instruction,
            model_config=mapping_conf
        )
        
        # Convert to dict
        mapping_dict = {
            "chart_type": mapping_spec.chart_type,
            "field_mappings": [
                {
                    "graph_field": m.graph_field,
                    "dataframe_column": m.dataframe_column,
                    "description": m.description
                }
                for m in mapping_spec.field_mappings
            ],
            "measure_columns": list(mapping_spec.measure_columns or []),
            "label_columns": list(mapping_spec.label_columns or []),
            "metadata_config": mapping_spec.metadata_config.model_dump(),
            "reasoning": mapping_spec.reasoning
        }
        
        logger.info(f"Mappings generated: {len(mapping_spec.field_mappings)} fields")

        # Record usage event for mapping step
        try:
            from agent.utils.usage_tracking import get_usage_tracker
            import asyncio
            from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model
            tracker = get_usage_tracker()
            owner_id = state.get("owner_id")
            # If mapping_spec has token metrics, use them; else, set to 0
            token_metrics = getattr(mapping_spec, "token_metrics", {}) or {}
            input_tokens = token_metrics.get("input_tokens", 0)
            output_tokens = token_metrics.get("output_tokens", 0)
            total_tokens = token_metrics.get("total_tokens", 0)
            # Determine key_type used
            prov_for_key = override_provider or get_provider_from_model(mapping_model or "")
            _, key_type = await get_owner_api_key_for_provider(owner_id, prov_for_key, return_source=True)
            key_type = key_type or "platform-key"
            asyncio.create_task(tracker.record_llm_call(
                owner_id=owner_id,
                agent_id=None,
                operation="chart_mapping",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                extra_metrics=[],
                key_type=key_type,
            ))
        except Exception:
            pass

        return {
            **state,
            "graph_mapping_spec": mapping_dict,
            "messages": state["messages"] + [AIMessage(content=f"Mappings for {chart_type}")]
        }
        
    except Exception as e:
        logger.error(f"Mapping error: {str(e)}", exc_info=True)
        return {**state, "error": f"Mapping error: {str(e)}"}


@track_time("Node: Assemble Graph Data")
async def assemble_graph_data_node(state: GraphAgentState) -> GraphAgentState:
    """
    Assemble complete graph data using mappings.
    Pure Python - NO LLM call.
    """
    logger.info("Assembling graph data (pure Python)")
    
    df = state["processed_dataframe"]
    mapping_spec = state["graph_mapping_spec"]
    
    if df is None or mapping_spec is None:
        logger.error("Missing DataFrame or mapping spec")
        return {**state, "error": "Missing DataFrame or mapping spec"}
    
    try:
        # Assemble data (pure Python)
        logger.info(f"Assembling {mapping_spec['chart_type']}")
        df, field_mappings = combine_label_columns(
            df, mapping_spec["field_mappings"], mapping_spec.get("label_columns")
        )
        graph_data = assemble_graph_data(
            df=df,
            chart_type=mapping_spec["chart_type"],
            field_mappings=field_mappings,
            metadata_config=mapping_spec["metadata_config"],
            verbose=True
        )
        
        logger.info(f"Graph assembled: {len(graph_data.get('data', []))} points")
        
        return {
            **state,
            "graph_data": graph_data,
            "messages": state["messages"] + [AIMessage(content=f"Graph assembled")]
        }
        
    except Exception as e:
        logger.error(f"Assembly error: {str(e)}", exc_info=True)
        return {**state, "error": f"Assembly error: {str(e)}"}


# ============================================================================
# SINGLE CONTROL FUNCTION
# ============================================================================

def should_continue(state: GraphAgentState) -> str:
    """Single control function to route the workflow."""
    # Check for errors first
    if state.get("error"):
        logger.warning("Error detected, ending workflow")
        return "end"
    
    # Route based on what's missing
    if state.get("processed_dataframe") is None:
        logger.debug("Need DataFrame")
        return "end"
    
    if not state.get("suggested_chart_type"):
        logger.debug("→ suggest_chart")
        return "suggest_chart"
    
    if not state.get("graph_mapping_spec"):
        logger.debug("→ generate_mapping")
        return "generate_mapping"
    
    if not state.get("graph_data"):
        logger.debug("→ assemble_graph")
        return "assemble_graph"
    
    logger.info("Workflow complete")
    return "end"
