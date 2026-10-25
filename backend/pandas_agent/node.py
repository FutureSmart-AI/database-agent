from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError
from typing import TypedDict, Annotated, Sequence, Literal, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
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

import os
from pandas_agent.models.pydantic_models import DataTransformationPlan
from pandas_agent.utils.util import get_dataframe_info, execute_pandas_operations
from langchain_community.callbacks import get_openai_callback
import operator
from logger import logger
from pandas_agent.utils.prompt import PLANNING_SYSTEM_PROMPT
from langgraph.graph import StateGraph, END
from agent.utils.owner_credential_utils import get_llm_api_key
from otel_tracing import track_time
from pandas_agent.utils.model_config_loader import load_model_config
from agent.utils.agent_config_loader import get_agent_node_config, merge_agent_config_with_defaults
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs

# State definition for Pandas Agent
class PandasAgentState(TypedDict):
    """State for the Pandas agent workflow."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    csv_path: str
    query: str
    chart_type: str | None
    plan: DataTransformationPlan | None
    execution_result: str | None
    error: str | None
    retry_count: int  # Track number of retries to prevent infinite loops
    # Aggregated token metrics for internal LLM calls (e.g., pandas_planning_*)
    token_metrics: Dict[str, Any] | None
    # Owner / usage context (for per-owner credentials & tracking)
    owner_id: str | None
    agent_id: str | None  # Agent ID for loading agent-specific configuration



# Create tools list and lookup dictionary
tools = [get_dataframe_info, execute_pandas_operations]
tools_by_name = {tool.name: tool for tool in tools}

@track_time("Node: Pandas Tool Execution")
async def tool_node(state: PandasAgentState) -> PandasAgentState:
    """Execute tool calls from the last message."""
    last_message = state["messages"][-1]
    
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return state
    
    result = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        logger.info(f"Executing tool: {tool_name}")
        
        # Skip if it's not a real tool (e.g., DataTransformationPlan schema)
        if tool_name not in tools_by_name:
            logger.warning(f"Tool {tool_name} not found in tools_by_name, skipping")
            continue
        
        tool = tools_by_name[tool_name]
        observation = await tool.ainvoke(tool_call["args"])
        result.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
    
    return {"messages": result}


@track_time("Node: Pandas Planning")
async def planning_node(state: PandasAgentState) -> PandasAgentState:
    """Node that plans the pandas transformations - OPTIMIZED to use only 1 LLM call."""
    logger.info(f"Planning node started - Query: {state['query'][:100]}")

    # Increment retry counter
    retry_count = state.get('retry_count', 0)
    if state.get('error'):  # Only increment if we're retrying due to error
        retry_count += 1

    # Check if we're re-planning due to an error
    previous_error = state.get('error')
    if previous_error:
        logger.info(f"Re-planning due to previous error (retry {retry_count}): {previous_error}")

    # Step 1: Get DataFrame info directly (no LLM needed)
    logger.info("Getting DataFrame info directly")
    try:
        df_info = await get_dataframe_info.ainvoke({"csv_path": state['csv_path']})
    except Exception as e:
        logger.error(f"Failed to get DataFrame info: {e}")
        return {
            **state,
            "plan": None,
            "error": f"Failed to analyze DataFrame: {str(e)}",
            "retry_count": retry_count
        }

    # Step 1.5: Check for empty dataset
    if "EMPTY_DATASET_DETECTED" in df_info:
        logger.warning("Empty dataset detected - returning empty result without processing")
        # Create a minimal plan that just creates an empty DataFrame
        from pandas_agent.models.pydantic_models import PandasOperation
        empty_plan = DataTransformationPlan(
            operations=[
                PandasOperation(
                    code="graph_df = pd.DataFrame()",
                    reason="Dataset is empty (SQL query returned no rows), creating empty DataFrame"
                )
            ],
            final_output="graph_df",
            reasoning="The source data is empty (SQL query returned zero rows). Returning an empty DataFrame."
        )
        return {
            **state,
            "plan": empty_plan,
            "error": None,
            "execution_result": "Empty dataset - no data to process",
            "messages": state["messages"] + [AIMessage(content="Empty dataset detected - no processing needed")],
            "retry_count": retry_count
        }

    # Step 2: Single LLM call to create the plan with structured output
    error_context = ""
    if previous_error:
        error_context = f"""
    PREVIOUS ATTEMPT FAILED WITH ERROR:
    {previous_error}

    Please create a NEW plan that avoids this error.
    """

    planning_prompt = f"""Based on the DataFrame analysis, create a transformation plan.

    CSV Path: {state['csv_path']}
    User Query: {state['query']}
    {error_context}
    DataFrame Analysis:
    {df_info}

    Create a complete DataTransformationPlan with:
    - operations: List of pandas operations to transform the data
    - final_output: Name of the final DataFrame variable
    - reasoning: Explanation of the transformation strategy

    CRITICAL RULES:
    - Do NOT include any plotting code (matplotlib, seaborn, plotly, etc.)
    - Only pandas data transformations are allowed
    - The final_output must be a valid Python variable name
    - Preserve ALL columns and grouping dimensions from the source data — do NOT
      aggregate or collapse categorical columns.
      Return the data at the finest grain needed to answer the query so that
      downstream chart selection can correctly visualise every group."""

    pandas_conf = operation_config("pandas_agent.default")
    pandas_model_name, pandas_provider = pandas_conf["model"], pandas_conf["provider"]

    if not pandas_model_name:
        logger.error("No pandas model specified in model_config.json")
        return {
            **state,
            "plan": None,
            "error": "PANDAS_MODEL is not configured",
            "retry_count": retry_count,
        }

    # Get per-owner API keys for Pandas LLM
    owner_id = state.get("owner_id")
    logger.info(f"🤖 [LLM_CALL] Pandas planning node | owner_id: {owner_id} | model: {pandas_model_name}")
    api_key = await get_llm_api_key(owner_id, pandas_model_name, pandas_provider) if pandas_model_name else None

    if api_key:
        logger.info(f"🚀 [LLM_CALL] Pandas planning node initialized | owner_id: {owner_id} | model: {pandas_model_name}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] Pandas planning node using default env credentials | owner_id: {owner_id} | model: {pandas_model_name}")

    # Dynamically select the model class based on provider
    provider_lower = pandas_provider.lower() if pandas_provider else "openai"

    if provider_lower == "groq":
        if ChatGroq is None:
            logger.error("ChatGroq not available but provider is groq")
            return {
                **state,
                "plan": None,
                "error": "ChatGroq not available",
                "retry_count": retry_count,
            }
        ModelClass = ChatGroq
    elif provider_lower == "anthropic":
        if ChatAnthropic is None:
            logger.error("ChatAnthropic not available but provider is anthropic")
            return {
                **state,
                "plan": None,
                "error": "ChatAnthropic not available",
                "retry_count": retry_count,
            }
        ModelClass = ChatAnthropic
    elif provider_lower == "google" or provider_lower == "gemini":
        if ChatGoogleGenerativeAI is None:
            logger.error(f"ChatGoogleGenerativeAI not available but provider is {provider_lower}")
            return {
                **state,
                "plan": None,
                "error": f"ChatGoogleGenerativeAI not available for {provider_lower}",
                "retry_count": retry_count,
            }
        ModelClass = ChatGoogleGenerativeAI
    else:
        ModelClass = ChatOpenAI

    ModelClass = configured_model_factory(pandas_conf)

    openai_kwargs = (
        structured_tool_chat_kwargs(pandas_model_name)
        if provider_lower in ("openai", "azure_openai")
        else {}
    )

    # OpenAI-compatible providers (deepseek/minimax) -> ChatOpenAI with their base_url + key.
    # api_key is overridden here (not stuffed into openai_kwargs) because the constructor
    # call below already passes api_key=api_key explicitly - putting it in both places
    # raises "got multiple values for keyword argument 'api_key'".
    from agent.utils.owner_credential_utils import get_openai_compatible_base_url, PROVIDER_ENV_MAP
    _base_url = get_openai_compatible_base_url(provider_lower)
    if _base_url:
        openai_kwargs = {**openai_kwargs, "base_url": _base_url}
        api_key = os.getenv(PROVIDER_ENV_MAP.get(provider_lower, ""))
        if provider_lower == "deepseek":  # V4 defaults to slow thinking mode - disable it
            openai_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    model = ModelClass(model=pandas_model_name, api_key=api_key, **openai_kwargs) if pandas_model_name else None
    if not model:
        logger.error("No PANDAS_MODEL configured")
        return {
            **state,
            "plan": None,
            "error": "PANDAS_MODEL is not configured",
            "retry_count": retry_count,
        }

    if provider_lower == "groq":
        try:
            structured_llm = model.with_structured_output(DataTransformationPlan)
            logger.info(f"✅ Groq structured output configured with JSON schema mode")
        except Exception as e:
            logger.error(f"Failed to configure Groq structured output: {e}")
            structured_llm = None
    elif provider_lower == "google":
        # Google GenAI doesn't support method="function_calling", use default structured output
        try:
            structured_llm = model.with_structured_output(DataTransformationPlan)
            logger.info(f"✅ Google structured output configured")
        except Exception as e:
            logger.error(f"Failed to configure Google structured output: {e}")
            structured_llm = None
    else:
        # OpenAI and other providers: use function_calling method
        structured_llm = model.with_structured_output(DataTransformationPlan, method="function_calling")

    # Wrap LLM calls in callback to capture token usage
    with get_openai_callback() as cb:
        plan = None
        exception_err = None
        used_model = None
        
        # Try primary model first
        if structured_llm:
            try:
                logger.debug(f"Calling primary model: {pandas_model_name} (provider: {provider_lower})")
                plan = await structured_llm.ainvoke([
                    SystemMessage(content=PLANNING_SYSTEM_PROMPT),
                    HumanMessage(content=planning_prompt)
                ])
                used_model = pandas_model_name
                logger.info(f"✅ Primary model ({pandas_model_name}) succeeded")
            except Exception as e:
                exception_err = e
                logger.error(f"❌ Primary model ({pandas_model_name}) failed | error_type: {type(e).__name__} | error: {str(e)[:200]}")
        else:
            exception_err = Exception("Structured LLM not initialized")
            logger.error(f"❌ Structured LLM not initialized for provider: {provider_lower}")
        
        # The selected provider/model is authoritative; no cross-model retry.

        # If both models failed, return error
        if not plan:
            logger.error(f"Failed to create plan with configured model {pandas_model_name}")
            error_str = str(exception_err) if exception_err else "Unknown error"
            if "get_dataframe_info" in error_str and "not in request.tools" in error_str:
                logger.warning("LLM tried to call get_dataframe_info tool during structured output - this is expected, retrying without tools")
                return {
                    **state,
                    "plan": None,
                    "error": "Validation failed: No plan found. Please create a valid DataTransformationPlan.",
                    "retry_count": retry_count
                }
            return {
                **state,
                "plan": None,
                "error": f"Failed to create transformation plan with configured model. Error: {str(exception_err)[:100]}",
                "retry_count": retry_count
            }

    # if not plan or not plan.operations:
    #     logger.error("Failed to create a valid plan")
    #     return {
    #         **state,
    #         "plan": None,
    #         "error": "Failed to create a valid transformation plan"
    #     }

    logger.info(f"✅ [PANDAS_PLANNING] Plan created successfully | model_used: {used_model} | operations: {len(plan.operations)}")
    logger.debug(f"Plan details: {plan}")

    # Aggregate token usage for pandas planning into token_metrics
    try:
        tokens_used = getattr(cb, "total_tokens", 0)
        input_tokens = getattr(cb, "prompt_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(cb, "input_tokens", None)
        output_tokens = getattr(cb, "completion_tokens", None)
        if output_tokens is None:
            output_tokens = getattr(cb, "output_tokens", None)

        token_metrics = dict(state.get("token_metrics") or {})
        # Per-node breakdown
        token_metrics["pandas_planning_input_tokens"] = float(token_metrics.get("pandas_planning_input_tokens", 0.0) + float(input_tokens or 0))
        token_metrics["pandas_planning_output_tokens"] = float(token_metrics.get("pandas_planning_output_tokens", 0.0) + float(output_tokens or 0))
        token_metrics["pandas_planning_total_tokens"] = float(token_metrics.get("pandas_planning_total_tokens", 0.0) + float(tokens_used or 0))
        # Aggregate totals used by graph agent bridge
        token_metrics["input_tokens"] = float(token_metrics.get("input_tokens", 0.0) + float(input_tokens or 0))
        token_metrics["output_tokens"] = float(token_metrics.get("output_tokens", 0.0) + float(output_tokens or 0))
        token_metrics["total_tokens"] = float(token_metrics.get("total_tokens", 0.0) + float(tokens_used or 0))
    except Exception:
        token_metrics = dict(state.get("token_metrics") or {})

    # Return the plan and a confirmation message. Clear error state for new plan.
    return {
        **state,
        "plan": plan,
        "error": None,  # Clear previous error when new plan is created
        "messages": state["messages"] + [AIMessage(content=f"Plan created: {plan.reasoning}")],
        "retry_count": retry_count,
        "token_metrics": token_metrics,
    }


def validation_node(state: PandasAgentState) -> PandasAgentState:
    """Node that validates the generated plan - ALL validation logic is here.

    Checks:
    1. Plan exists and has operations
    2. No forbidden plotting code (matplotlib, seaborn, plotly, etc.)
    3. Valid final_output variable name
    4. Operations have valid code
    
    On validation error, sets detailed `error` message and returns state so 
    the graph routes back to planning for correction with error context.
    """
    logger.info("Validation node started")

    plan = state.get("plan")
    if not plan:
        logger.error("No plan found during validation")
        return {
            **state,
            "error": "Validation failed: No plan found. Please create a valid DataTransformationPlan.",
            "messages": state.get("messages", []) + [AIMessage(content="Validation failed: no plan")]
        }

    # Check if plan has operations
    if not plan.operations or len(plan.operations) == 0:
        logger.error("Plan has no operations")
        return {
            **state,
            "error": "Validation failed: Plan contains no operations. Please create at least one pandas operation to transform the data.",
            "messages": state.get("messages", []) + [AIMessage(content="Validation failed: no operations")]
        }

    # Check for forbidden plotting code
    forbidden = ['matplotlib', 'plt.', 'seaborn', 'sns.', 'plotly', 'px.', 'go.',
                 'plot(', 'bar(', 'scatter(', 'figure', 'ax.', 'show()', '.plot', '.bar', '.scatter']

    for i, op in enumerate(plan.operations, start=1):
        op_text = (op.code or "").lower()
        for kw in forbidden:
            if kw in op_text:
                logger.error(f"Validation failed: plotting code '{kw}' detected in operation {i}")
                error_msg = (
                    f"Validation failed: Forbidden plotting code '{kw}' detected in operation {i}. "
                    f"CRITICAL RULE: Do NOT include any plotting code (matplotlib, plt., seaborn, sns., plotly, px., go., or any .plot(), .bar(), .scatter() methods). "
                    f"Only pandas data transformation operations are allowed. Remove all plotting code and use only pandas operations."
                )
                return {
                    **state,
                    "error": error_msg,
                    "messages": state.get("messages", []) + [AIMessage(content=f"Validation failed: plotting code '{kw}' found")]
                }

    # Validate final_output is a valid Python variable name
    if not plan.final_output:
        logger.error("final_output is missing")
        return {
            **state,
            "error": "Validation failed: final_output is missing. Please specify the name of the final DataFrame variable.",
            "messages": state.get("messages", []) + [AIMessage(content="Validation failed: no final_output")]
        }
    
    if not plan.final_output.isidentifier():
        logger.error(f"Invalid final_output variable name: {plan.final_output}")
        return {
            **state,
            "error": f"Validation failed: final_output '{plan.final_output}' is not a valid Python variable name. Use only letters, numbers, and underscores, and start with a letter or underscore.",
            "messages": state.get("messages", []) + [AIMessage(content="Validation failed: invalid final_output name")]
        }

    # Check that operations have code
    for i, op in enumerate(plan.operations, start=1):
        if not op.code or not op.code.strip():
            logger.error(f"Operation {i} has no code")
            return {
                **state,
                "error": f"Validation failed: Operation {i} has no code. Each operation must contain valid pandas code.",
                "messages": state.get("messages", []) + [AIMessage(content=f"Validation failed: operation {i} has no code")]
            }

    logger.info("Validation passed - all checks successful")
    return {
        **state,
        "error": None,  # Clear error on successful validation
        "messages": state.get("messages", []) + [AIMessage(content="Validation passed - plan is valid")]
    }


def validation_decision(state: PandasAgentState) -> str:
    """Decision function for validation node: on success -> execute, on failure -> planning."""
    # Check retry limit to prevent infinite loops
    retry_count = state.get("retry_count", 0)
    MAX_RETRIES = 5

    if retry_count >= MAX_RETRIES:
        logger.error(f"Maximum retry limit ({MAX_RETRIES}) reached. Stopping execution.")
        return "execute"  # Force execution to end the loop, even with errors

    if state.get("error"):
        logger.warning(f"Validation error detected; returning to planning (retry {retry_count + 1}/{MAX_RETRIES})")
        return "planning"
    if not state.get("plan"):
        logger.warning(f"Validation found no plan; returning to planning (retry {retry_count + 1}/{MAX_RETRIES})")
        return "planning"
    return "execute"


def execution_decision(state: PandasAgentState) -> str:
    """Decision after execution: on error -> planning, otherwise end."""
    # Check retry limit to prevent infinite loops
    retry_count = state.get("retry_count", 0)
    MAX_RETRIES = 5

    if retry_count >= MAX_RETRIES:
        logger.error(f"Maximum retry limit ({MAX_RETRIES}) reached. Ending execution.")
        return "end"  # Force end even with errors

    if state.get("error"):
        logger.warning(f"Execution error detected; returning to planning (retry {retry_count + 1}/{MAX_RETRIES})")
        return "planning"
    return "end"


async def execution_node(state: PandasAgentState) -> PandasAgentState:
    """Node that executes the pandas operations - NO LLM call needed."""
    logger.info("Execution node started")
    
    if not state.get("plan"):
        logger.error("No plan available for execution")
        return {
            **state,
            "error": "No plan available for execution"
        }
    
    plan = state["plan"]
    logger.debug(f"Executing plan with {len(plan.operations)} operations")
    
    # Combine all operations
    all_operations = "\n\n".join([
        f"# {op.reason}\n{op.code}"
        for op in plan.operations
    ])
    
    # Direct tool execution - NO LLM call
    logger.info("Executing pandas operations directly")
    
    try:
        result = await execute_pandas_operations.ainvoke({
            "csv_path": state['csv_path'],
            "operations": all_operations,
            "final_output": plan.final_output
        })
    except Exception as e:
        error_msg = f"Execution error: {str(e)}"
        logger.error(error_msg)
        return {
            **state,
            "error": error_msg,
            "messages": state["messages"] + [AIMessage(content=error_msg)]
        }
    
    logger.info("Operations execution completed")
    logger.debug(f"Result: {result[:200]}...")
    
    # Check for errors
    if result.lower().startswith("error"):
        logger.error(f"Execution error: {result[:100]}")
        return {
            **state,
            "execution_result": result,
            "error": result,
            "messages": state["messages"] + [AIMessage(content=f"Execution failed: {result}")]
        }
    
    logger.info("Execution completed successfully")
    return {
        **state,
        "execution_result": result,
        "messages": state["messages"] + [AIMessage(content="Execution completed successfully")]
    }


def should_continue(state: PandasAgentState) -> str:
    """Decide whether to continue or end."""
    if state.get("error"):
        logger.warning("Error detected, ending execution")
        return "end"
    if not state.get("plan"):
        logger.warning("No plan created, ending execution")
        return "end"
    logger.info("Continuing to execution node")
    return "execute"
