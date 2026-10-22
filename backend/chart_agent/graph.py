from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError
"""
Graph Agent as a LangGraph workflow.
Uses Pandas Agent as a subgraph to process CSV and generate graph data.
Includes intelligent routing to determine if pandas agent is needed.
"""

from typing import List, Optional, Literal
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks import get_openai_callback
from pydantic import BaseModel, Field
import os
try:
    from langchain_groq import ChatGroq
    ChatModel = ChatGroq
except Exception:
    from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
    ChatModel = ChatOpenAI

from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI

try:
    from groq import RateLimitError as GroqRateLimitError, BadRequestError as GroqBadRequestError  # type: ignore
except Exception:  # pragma: no cover - groq SDK not installed
    GroqRateLimitError = Exception  # type: ignore[misc,assignment]
    GroqBadRequestError = Exception  # type: ignore[misc,assignment]

try:
    from openai import BadRequestError as OpenAIBadRequestError
except Exception:  # pragma: no cover - openai SDK not installed
    OpenAIBadRequestError = Exception  # type: ignore[misc,assignment]

import pandas as pd
from chart_agent.models.graph_pydantic_models import (
    ChartType, GraphResponse, DataFrameStructure
)
from chart_agent.node import (
    invoke_pandas_agent,
    validate_chart_type_node,
    GraphAgentState,
    generate_graph_mapping_node,
    assemble_graph_data_node
)
from agent.utils.owner_credential_utils import get_llm_api_key, get_provider_from_model
from chart_agent.utils.model_config_loader import load_model_config
from logger import logger
from otel_tracing import track_time
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs


# ============================================================================
# ROUTING LOGIC WITH NEW SCHEMA
# ============================================================================

class GraphRouterOutput(BaseModel):
    """Graph router handles query refinement, chart suggestion, and routing."""

    action: Literal["END", "invoke_pandas_agent"] = Field(
        ..., description="END for greetings/errors/clarifications, invoke_pandas_agent for all visualization requests"
    )

    chart_type: Optional[str] = Field(
        None, description="Suggested chart type from supported options. None if action=END"
    )

    refined_query: str = Field(
        ..., description="Visualization query with history resolved"
    )

    response: Optional[str] = Field(
        None, description="Direct response. Only when action=END"
    )


def get_graph_router_prompt():
    """Get the router prompt for the graph agent."""
    system_role = """Analyze visualization requests and route appropriately.

**Routing:**
- END: Any of the conditions below where charting adds no value
- invoke_pandas_agent: Only when a chart genuinely communicates the data better than text

**WHEN TO ROUTE TO END (no chart):**
1. **Single scalar result** — DATA_SHAPE shows 1 row × 1 column. A single number needs no chart.
2. **Single-answer query intent** — The query asks for a single aggregate value (one scalar — total, count, average, sum, min, max, ratio, percentage, or similar). Recognize this from the meaning of the query, not from specific phrasing.
3. **Flat key-value summary** — DATA_SHAPE is 1 row × N columns (one record with multiple fields). A chart of one entity's attributes is meaningless.
4. **Too few data points** — DATA_SHAPE shows fewer than 2 rows of actual data categories.
5. **Missing or empty dataframe** — HAS_DATAFRAME is False or DATA_SHAPE is 0 rows.
6. **Greetings / capability questions / unclear requests.**

**WHEN TO ROUTE TO invoke_pandas_agent (generate chart):**
- 2+ categories or time periods being compared
- Trends over multiple time points
- Distribution across multiple groups
- Part-to-whole relationships with multiple slices
- Correlation between two numeric variables across multiple records

**CHART SELECTION GUIDELINES (only when charting is appropriate):**
- **Stacked Bar Chart**: Multiple metrics, grouping, sub-categories, or segmentation.
- **Bar Chart / Column Chart**: Single metric categorical comparisons across 2+ categories.
- **Line Chart**: Single continuous trend over multiple time points. Do not use for grouped/segmented views.
- **Pie Chart**: Part-to-whole with a single metric and 2–6 slices.
- **Scatter Chart**: Correlation between two numeric variables across multiple records.
- **Bubble Chart**: Three numeric variables (x, y, size) across multiple records.
- **Geo Chart**: Geographic data with country/region codes across multiple locations.

**COLUMN-AWARE SELECTION RULES (read DATA_SHAPE column names carefully):**
- If DATA_SHAPE shows a MULTI-SERIES flag, the data is in long format with a grouping dimension. Use **Stacked Bar Chart** regardless of what the user asked for — any other chart will silently drop data.
- If column names include a categorical grouping column (a column with a small, repeated set of distinct string values such as `status`, `category`, `type`, `segment`, `group`, or `dimension`) alongside an axis column and a numeric column → long-format multi-series → **Stacked Bar Chart**.
- If column names include a geographic identifier (country, region, state, city, or ISO code) → **Geo Chart**.

**OVERRIDE RULE — Data structure wins over user's stated chart preference:**
Even if the user explicitly requests a specific chart type, override it when the data structure makes that chart wrong or lossy:
- User asks for Line/Bar/Column Chart but DATA_SHAPE shows MULTI-SERIES or a grouping column → **Stacked Bar Chart**.
- User asks for Pie Chart but more than 8 distinct values → **Bar Chart**.
- User asks for Line Chart but data has only 1 data point → **Bar Chart**.
The refined_query should still reflect what the user wanted to see, just with the correct chart type applied.

`chart_type` must be exactly one of the supported chart names below. Do not modify or add words.
Supported visualizations: {supported_graphs}

If the query contains terms suggesting comparison, grouping, or breakdown (e.g. "grouped", "segmented", "broken down by", "split by", "comparing X and Y", "by <dimension>"), prefer **Stacked Bar Chart**.

**Refinement:**
Resolve history references to make the query standalone."""

    return ChatPromptTemplate.from_messages([
        ("system", system_role),
        ("human", "CONVERSATION LOG:\n{messages}\n\nQUERY: {query}\n\nHAS_DATAFRAME: {has_dataframe}\nDATA_SHAPE: {data_shape}")
    ])



@track_time("Node: Route Graph Query")
async def route_query(state: GraphAgentState) -> GraphAgentState:
    """
    Router node: determines routing, suggests chart type, and refines query.
    
    Smart chart selection:
    - If 1 allowed_graph: use it directly (no LLM call needed)
    - If 2+ allowed_graphs: use LLM to pick best fit
    - If no allowed_graphs: use LLM with all available charts
    """
    question = state["question"]
    csv_path = state.get("csv_path")
    has_dataframe = csv_path is not None and csv_path != ""

    logger.info(f"🔀 Routing graph query: {question[:100]}")
    logger.info(f"   Has dataframe: {has_dataframe}")

    # --- Pre-LLM heuristic: inspect data shape before spending any tokens ---
    data_shape = "unknown"
    if has_dataframe and csv_path and os.path.exists(csv_path):
        try:
            _df = pd.read_csv(csv_path)
            n_rows, n_cols = _df.shape
            col_names = list(_df.columns)
            # Flag long-format multi-series: 3 cols, 1 numeric, a string col with few unique values
            # that causes duplicate values in what looks like the axis column.
            multi_series_hint = ""
            try:
                numeric_cols = [c for c in col_names if pd.api.types.is_numeric_dtype(_df[c])]
                str_cols = [c for c in col_names if _df[c].dtype == object]
                if n_cols == 3 and len(numeric_cols) == 1 and len(str_cols) >= 1:
                    for sc in str_cols:
                        n_uniq = _df[sc].nunique()
                        if 2 <= n_uniq <= 20 and _df[sc].duplicated().any():
                            multi_series_hint = (
                                f" | MULTI-SERIES: column '{sc}' has {n_uniq} unique values "
                                f"and repeats across rows — this is long-format grouped data"
                            )
                            break
            except Exception:
                pass
            data_shape = f"{n_rows} rows × {n_cols} columns | columns: {', '.join(col_names)}{multi_series_hint}"
            logger.info(f"   Data shape: {data_shape}")

            if n_rows == 0:
                logger.info("   ↳ Empty result — routing to END (no chart)")
                state.update(action="END", chart_type=None, refined_query=question, response=None)
                return state

            if n_rows == 1 and n_cols == 1:
                logger.info("   ↳ Single scalar value — routing to END (chart adds no value)")
                state.update(action="END", chart_type=None, refined_query=question, response=None)
                return state

            if n_rows == 1:
                logger.info(f"   ↳ Single-row result ({n_cols} cols) — routing to END (one entity, no comparison)")
                state.update(action="END", chart_type=None, refined_query=question, response=None)
                return state

        except Exception as e:
            logger.warning(f"   Could not read CSV for shape check: {e}")

    # Get allowed graphs for the prompt
    allowed_graphs = state.get("allowed_graphs", None)

    # OPTIMIZATION: If only 1 allowed chart, use it directly without LLM call
    if allowed_graphs and len(allowed_graphs) == 1:
        single_chart = allowed_graphs[0]
        logger.info(f"   ✓ Single allowed chart: {single_chart.value} (skipping LLM)")
        state["action"] = "invoke_pandas_agent"
        state["chart_type"] = single_chart.value
        state["refined_query"] = question
        state["response"] = None
        state["suggested_chart_type"] = single_chart
        return state
    
    # Multiple allowed graphs or no restriction - use LLM to decide
    if allowed_graphs:
        supported_graphs = ", ".join([g.value for g in allowed_graphs])
        logger.info(f"   Multiple allowed charts ({len(allowed_graphs)}): using LLM to select")
    else:
        # Default supported graphs
        supported_graphs = "Bar Chart, Column Chart, Pie Chart, Line Chart, Stacked Bar Chart, Bubble Chart, Scatter Chart, Geo Chart"
        logger.info(f"   No chart restrictions: using LLM to select from all")

    # Get conversation history
    messages_str = "\n".join([f"{msg.type}: {msg.content}" for msg in state.get("messages", [])])

    # Base router prompt
    base_prompt = get_graph_router_prompt()

    # Optional overrides injected from the main nl2sql agent
    override_model = state.get("chart_agent_model")
    override_provider = state.get("chart_agent_provider")
    override_prompt = state.get("chart_agent_prompt")

    # If an override prompt is provided, append it as additional instructions
    if override_prompt:
        try:
            messages_tpl = base_prompt.messages
            if messages_tpl and len(messages_tpl) > 0:
                # Extract original system template
                system_template = (
                    messages_tpl[0].prompt.template
                    if hasattr(messages_tpl[0], "prompt") and hasattr(messages_tpl[0].prompt, "template")
                    else str(messages_tpl[0])
                )
                enhanced_system = (
                    f"{system_template}\n\n"
                    f"**Additional Instructions for chart_agent (router):**\n{override_prompt}"
                )

                # Extract human template (fall back to default if necessary)
                if len(messages_tpl) > 1 and hasattr(messages_tpl[1], "prompt") and hasattr(messages_tpl[1].prompt, "template"):
                    human_template = messages_tpl[1].prompt.template
                else:
                    human_template = "CONVERSATION LOG:\n{messages}\n\nQUERY: {query}\n\nHAS_DATAFRAME: {has_dataframe}"

                prompt = ChatPromptTemplate.from_messages(
                    [("system", enhanced_system), ("human", human_template)]
                )
            else:
                prompt = base_prompt
        except Exception:
            # On any error, fall back to base prompt to avoid breaking routing
            prompt = base_prompt
    else:
        prompt = base_prompt

    if override_prompt:
        try:
            logger.info(f"✅ Router additional_instruction length={len(override_prompt)}")
        except Exception:
            pass

    override = state.get("chart_agent_config")
    if override is None and (override_model or override_provider):
        override = {"model": override_model, "provider": override_provider}
    router_conf = operation_config("chart_agent.router", override)
    model_name, provider = router_conf["model"], router_conf["provider"]
    owner_id = state.get("owner_id")
    
    # Get API keys with logging - pass provider so correct key is loaded
    logger.info(f"🤖 [LLM_CALL] Chart Router node | owner_id: {owner_id} | model: {model_name} | provider: {provider}")
    api_key = await get_llm_api_key(owner_id, model_name, provider)
    
    # Log which credential source is being used
    if api_key:
        logger.info(f"🚀 [LLM_CALL] Chart Router node initialized | owner_id: {owner_id} | model: {model_name} | provider: {provider}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] Chart Router node using default env credentials | owner_id: {owner_id} | model: {model_name} | provider: {provider}")

    # Dynamically select the model class based on provider
    try:
        from langchain_groq import ChatGroq as GroqModel
        groq_available = True
    except Exception:
        groq_available = False
        GroqModel = None
    
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI as GoogleModel
        google_available = True
    except Exception:
        google_available = False
        GoogleModel = None
        
    try:
        from langchain_anthropic import ChatAnthropic as AnthropicModel
        anthropic_available = True
    except Exception:
        anthropic_available = False
        AnthropicModel = None
    
    if provider == "groq":
        if not groq_available or GroqModel is None:
            logger.error("ChatGroq not available but provider is groq")
            return {
                **state,
                "action": "END",
                "response": "Configuration error: Groq provider not available",
                "chart_type": None,
                "refined_query": question
            }
        ModelClass = GroqModel
    elif provider == "google" or provider == "gemini":
        if not google_available or GoogleModel is None:
            logger.error(f"ChatGoogleGenerativeAI not available but provider is {provider}")
            return {
                **state,
                "action": "END",
                "response": f"Configuration error: {provider} provider not available",
                "chart_type": None,
                "refined_query": question
            }
        ModelClass = GoogleModel
    elif provider == "anthropic":
        if not anthropic_available or AnthropicModel is None:
            logger.error("ChatAnthropic not available but provider is anthropic")
            return {
                **state,
                "action": "END",
                "response": "Configuration error: Anthropic provider not available",
                "chart_type": None,
                "refined_query": question
            }
        ModelClass = AnthropicModel
    else:
        ModelClass = ChatOpenAI
    
    ModelClass = configured_model_factory(router_conf)

    openai_kwargs = (
        structured_tool_chat_kwargs(model_name)
        if provider in ("openai", "azure_openai")
        else {}
    )

    llm = ModelClass(model=model_name, api_key=api_key, **openai_kwargs) if api_key else ModelClass(model=model_name, **openai_kwargs)
    # Choose structured output mode depending on provider: Groq prefers JSON-schema (no function calling),
    # Google doesn't support method="function_calling", other providers use function-calling style
    is_groq = (provider == "groq" and groq_available)
    is_google = (provider == "google" and google_available)

    # For Groq, try json_schema method explicitly to avoid function calling issues
    if is_groq:
        try:
            # Try json_schema method first (explicit JSON mode)
            structured_llm = llm.with_structured_output(GraphRouterOutput, method="json_schema")
        except Exception:
            # Fallback to default (some Groq models may not support json_schema parameter)
            structured_llm = llm.with_structured_output(GraphRouterOutput)
    elif is_google:
        # Google GenAI doesn't support method="function_calling", use default structured output
        structured_llm = llm.with_structured_output(GraphRouterOutput)
    else:
        # OpenAI and other providers: use function_calling method
        structured_llm = llm.with_structured_output(GraphRouterOutput, method="function_calling")
    chain = prompt | structured_llm

    # Capture token usage for graph router
    with get_openai_callback() as cb:
        try:
            router_output = await chain.ainvoke(
                {
                    "messages": messages_str if messages_str else "No previous conversation",
                    "query": question,
                    "has_dataframe": str(has_dataframe),
                    "supported_graphs": supported_graphs,
                    "data_shape": data_shape,
                })
        except (GroqRateLimitError, GroqBadRequestError, OpenAIBadRequestError) as err:
            logger.error("Chart router configured model failed: %s", type(err).__name__)
            return {**state, "action": "END", "response": "Configured chart model request failed.",
                    "chart_type": None, "refined_query": question}

    d = dict(router_output) if not isinstance(router_output, dict) else router_output

    # Aggregate router token metrics into graph state
    try:
        tokens_used = getattr(cb, "total_tokens", 0)
        input_tokens = getattr(cb, "prompt_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(cb, "input_tokens", None)
        output_tokens = getattr(cb, "completion_tokens", None)
        if output_tokens is None:
            output_tokens = getattr(cb, "output_tokens", None)

        token_metrics = dict(state.get("token_metrics") or {})
        token_metrics["graph_router_input_tokens"] = float(token_metrics.get("graph_router_input_tokens", 0.0) + float(input_tokens or 0))
        token_metrics["graph_router_output_tokens"] = float(token_metrics.get("graph_router_output_tokens", 0.0) + float(output_tokens or 0))
        token_metrics["graph_router_total_tokens"] = float(token_metrics.get("graph_router_total_tokens", 0.0) + float(tokens_used or 0))
        # Aggregated totals used by graph_agent_bridge
        token_metrics["input_tokens"] = float(token_metrics.get("input_tokens", 0.0) + float(input_tokens or 0))
        token_metrics["output_tokens"] = float(token_metrics.get("output_tokens", 0.0) + float(output_tokens or 0))
        token_metrics["total_tokens"] = float(token_metrics.get("total_tokens", 0.0) + float(tokens_used or 0))
        state["token_metrics"] = token_metrics

        # Record usage event for router step
        try:
            from agent.utils.usage_tracking import get_usage_tracker
            import asyncio
            from agent.utils.owner_credential_utils import get_owner_api_key_for_provider
            tracker = get_usage_tracker()
            owner_id = state.get("owner_id")
            try:
                _, key_type = await get_owner_api_key_for_provider(owner_id, provider, return_source=True)
                key_type = key_type or "platform-key"
            except Exception:
                key_type = "platform-key"
            asyncio.create_task(tracker.record_llm_call(
                owner_id=owner_id,
                agent_id=None,
                operation="chart_router",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=tokens_used,
                extra_metrics=[],
                key_type=key_type,
            ))
        except Exception:
            pass
    except Exception:
        # Metrics must never break routing
        pass

    logger.info(f"   Action: {d.get('action')}")
    logger.info(f"   Chart type: {d.get('chart_type')}")
    logger.info(f"   Response: {d.get('response', 'None')[:50] if d.get('response') else 'None'}")

    # Update state with router outputs
    state["action"] = d.get("action", "END")
    state["chart_type"] = d.get("chart_type")
    state["refined_query"] = d.get("refined_query", question)
    state["response"] = d.get("response")

    # Also set suggested_chart_type for compatibility with existing nodes
    if d.get("chart_type"):
        # Convert string to ChartType enum
        try:
            chart_type_enum = ChartType(d.get("chart_type"))
            state["suggested_chart_type"] = chart_type_enum
            logger.info(f"   ✓ Chart type validated: {chart_type_enum.value}")
        except ValueError:
            logger.warning(f"   Invalid chart type from router: {d.get('chart_type')}")
            # Fallback: use first allowed chart if available
            if allowed_graphs and len(allowed_graphs) > 0:
                fallback_chart = allowed_graphs[0]
                state["suggested_chart_type"] = fallback_chart
                state["chart_type"] = fallback_chart.value
                logger.info(f"   ✓ Using fallback chart type: {fallback_chart.value}")
            else:
                logger.error(f"   No fallback available - chart type will be None")

    return state

def route_decision(state: GraphAgentState) -> str:
    """
    Conditional edge function for routing based on action.
    """
    action = state.get("action", "END")
    if action == "invoke_pandas_agent":
        return "invoke_pandas_agent"
    else:
        return "END"

# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

def create_graph_agent_graph():
    """
    Create the Graph agent workflow with smart routing.

    Flow: route → [END or pandas → mapping → assembly → END]
    Chart type is suggested by router. Errors are handled within nodes.
    """
    logger.info("Creating Graph agent with smart router + mapper + assembler")
    workflow = StateGraph(GraphAgentState)

    # Add nodes (no suggest_chart node - router handles chart suggestion)
    workflow.add_node("route_query", route_query)
    workflow.add_node("invoke_pandas_agent", invoke_pandas_agent)
    workflow.add_node("validate_chart_type", validate_chart_type_node)
    workflow.add_node("generate_mapping", generate_graph_mapping_node)
    workflow.add_node("assemble_graph", assemble_graph_data_node)

    # Entry point - router first
    workflow.set_entry_point("route_query")

    # Routing decision after router
    workflow.add_conditional_edges(
        "route_query",
        route_decision,
        {
            "invoke_pandas_agent": "invoke_pandas_agent",
            "END": END
        }
    )

    # Linear flow: pandas → validate → mapping → assembly → END
    workflow.add_edge("invoke_pandas_agent", "validate_chart_type")
    workflow.add_edge("validate_chart_type", "generate_mapping")
    workflow.add_edge("generate_mapping", "assemble_graph")
    workflow.add_edge("assemble_graph", END)

    logger.info("Graph agent created with linear flow: route -> pandas -> validate -> mapping -> assembly")
    return workflow.compile()


# Create the compiled graph
graph_agent_graph = create_graph_agent_graph()


# ============================================================================
# HELPER FUNCTION
# ============================================================================

async def generate_graph_from_csv(
    csv_path: str, 
    question: str, 
    allowed_graphs: List[ChartType] | None = None,
    owner_id: str | None = None
) -> GraphResponse | dict:
    """
    Generate graph data from CSV using mapper + assembler approach.
    
    Args:
        csv_path: Path to CSV file
        question: Natural language question
        allowed_graphs: Optional list of allowed chart types
        
    Returns:
        GraphResponse with complete graph data or dict with direct response for non-data queries
    """
    logger.info(f"Starting graph generation")
    logger.info(f"   Question: {question[:100]}")
    logger.info(f"   Allowed: {[g.value for g in allowed_graphs] if allowed_graphs else 'All'}")
    
    initial_state = {
        "messages": [],
        "csv_path": csv_path,
        "question": question,
        "allowed_graphs": allowed_graphs,
        "owner_id": owner_id,
        "processed_dataframe": None,
        "suggested_chart_type": None,
        "graph_mapping_spec": None,
        "graph_data": None,
        "error": None,
        "action": None,
        "chart_type": None,
        "refined_query": None,
        "response": None
    }

    result = await graph_agent_graph.ainvoke(initial_state)

    # Handle direct responses (router decided action=END)
    if result.get("action") == "END" and result.get("response"):
        logger.info(f"Direct response from router")
        # Return a dict with special marker
        return {
            "is_direct_response": True,
            "response": result["response"],
            "chart_type": result.get("chart_type")
        }
    
    # Handle errors
    if result.get("error"):
        logger.error(f"Generation failed: {result['error']}")
        raise Exception(result["error"])
    
    # Handle graph generation
    chart_type = result["suggested_chart_type"]
    graph_data = result["graph_data"]
    
    logger.info(f"Generation complete: {chart_type}")
    logger.info(f"   Data points: {len(graph_data.get('data', []))}")
    
    # Convert DataFrame to structure
    df = result["processed_dataframe"]
    dataframe_struct = DataFrameStructure(
        columns=df.columns.tolist(),
        data=df.to_dict(orient='records'),
        shape=[df.shape[0], df.shape[1]],
        dtypes={col: str(df[col].dtype) for col in df.columns}
    )
    
    return GraphResponse(
        graph_suggestion=chart_type,
        graph_data=graph_data,
        dataframe=dataframe_struct,
        token_metrics=result.get("token_metrics")
    )
