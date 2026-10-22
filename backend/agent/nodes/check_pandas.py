from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError
from typing import Literal
from agent.state import AgentState
from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI

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

try:
    from groq import RateLimitError as GroqRateLimitError  # type: ignore
except Exception:  # pragma: no cover - groq SDK not installed
    GroqRateLimitError = Exception  # type: ignore[misc,assignment]

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.callbacks import get_openai_callback
from pydantic import BaseModel, Field
from logger import logger
import os
from agent.utils.model_config_loader import load_model_config
from agent.utils.agent_config_loader import get_agent_node_config, merge_agent_config_with_defaults
from otel_tracing import track_time
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs


class PandasRoutingDecision(BaseModel):
    """Decision on whether to use pandas agent for further processing."""
    needs_pandas: bool = Field(description="True if the query requires complex aggregation or analysis that SQL couldn't fully handle or if the user explicitly asks for analysis.")
    reasoning: str = Field(description="Reasoning for the decision.")


# Analysis-intent keywords used by the LLM-failure fallback below.
_ANALYSIS_KEYWORDS = [
    "analysis", "analyze", "trend", "summary", "distribution", "correlation",
    "aggregate", "average", "mean", "median", "std", "variance", "regression",
    "plot", "visual", "chart", "compare", "rolling", "time series", "time-series",
]

@track_time("Node: Check Pandas")
async def check_pandas_needed(state: AgentState) -> Literal["invoke_pandas", "final_answer_node"]:
    """
    Determines if the Pandas Agent should be invoked based on the query and SQL results.
    """
    logger.info("Checking if Pandas Agent is needed...")
    
    query = state.get("query", "")
    sql_query = state.get("sql_query", "")
    db_result = state.get("db_result", [])
    
    # If no results, no point in pandas
    if not db_result:
        logger.info("No DB results, skipping Pandas Agent")
        return "final_answer_node"

    # If results are very small (e.g. single value), unlikely to need pandas unless explicitly asked
    # But let the LLM decide based on the query intent

    system_prompt = """You are an intelligent router for a SQL-based data agent.
    The agent has already executed a SQL query and got some results.
    Your job is to decide if we need to pass these results to a Pandas-based data analysis agent for further processing.
    
    Use the Pandas Agent if:
    1. The user asks for "analysis", "correlation", "trend", "summary", "distribution", or complex statistics.
    2. The SQL query returned raw data that needs to be aggregated or transformed in ways that are hard/impossible in standard SQL (e.g. complex time-series analysis, linear regression, etc.).
    3. The user asks for a textual summary of the data patterns.
    
    Do NOT use the Pandas Agent if:
    1. The user just asked for a list of items or a simple count/sum that SQL already calculated.
    2. The SQL result is already the final answer (e.g. "What is the total sales?" -> 1000).
    """
    
    user_message = f"""
    User Query: {query}
    Executed SQL: {sql_query}
    Result Sample (first 3 rows): {str(db_result)[:500]}
    Result Count: {len(db_result) if isinstance(db_result, list) else 1}
    """
    
    # If the caller explicitly requested a visualization or graph output, prefer pandas
    # if state.get("visualization_query") or state.get("include_graph_output") or state.get("graph_output"):
    #     logger.info("Visualization requested or graph_output flag set — invoking Pandas agent")
    #     return "invoke_pandas"

    try:
        node_config = operation_config("sql_agent.check_pandas")
        model_name, provider = node_config["model"], node_config["provider"]
        llm = build_chat_model(node_config)

        # Try multiple structured output modes to support different provider clients (Groq vs OpenAI)
        decision = None
        last_exc = None

        # OpenAI and Groq both require the word 'json' in messages when using json_mode
        # Add JSON instruction to the system prompt for all providers
        system_prompt += "\n\nIMPORTANT: Return the decision as a JSON object. Use the keys 'needs_pandas' (boolean) and 'reasoning' (string)."

        # Capture token usage for the decision LLM call
        with get_openai_callback() as cb:
            import time
            llm_start_time = time.time()
            for method in ((None,) if provider == "google" else ("json_mode",) if provider == "deepseek" else ("function_calling",)):
                try:
                    if method is None:
                        structured_llm = llm.with_structured_output(PandasRoutingDecision)
                    else:
                        structured_llm = llm.with_structured_output(PandasRoutingDecision, method=method)

                    decision = await structured_llm.ainvoke([
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_message)
                    ])
                    # If we got a response, stop trying other methods
                    break
                except Exception as e:
                    last_exc = e
                    continue

        if decision is None:
            # No LLM decision; log and fall back
            logger.warning(f"Pandas LLM decision unavailable, last error: {last_exc}")
            raise last_exc

        # The structured LLM may return a Pydantic model or a dict-like object
        needs_pandas = getattr(decision, "needs_pandas", None)
        reasoning = getattr(decision, "reasoning", None)
        if needs_pandas is None and isinstance(decision, dict):
            needs_pandas = decision.get("needs_pandas")
            reasoning = decision.get("reasoning")

        logger.info(f"Pandas Routing Decision: {needs_pandas} ({reasoning})")

        # LLM USAGE TRACKING for check_pandas_needed node
        try:
            from agent.utils.usage_tracking import get_usage_tracker
            from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model
            llm_end_time = time.time()
            tracker = get_usage_tracker()
            execution_time = (llm_end_time - llm_start_time) if "llm_start_time" in locals() else 0
            tokens_used = getattr(cb, "total_tokens", 0)
            input_tokens = getattr(cb, "prompt_tokens", None)
            if input_tokens is None:
                input_tokens = getattr(cb, "input_tokens", None)
            output_tokens = getattr(cb, "completion_tokens", None)
            if output_tokens is None:
                output_tokens = getattr(cb, "output_tokens", None)

            duration_ms = float(execution_time * 1000.0)
            temperature = node_config.get("temperature", 0.0) if node_config else 0.0
            metadata = {
                "model": model_name,
                "provider": provider,
                "temperature": temperature,
            }
            try:
                prov_for_key = provider or get_provider_from_model(model_name or "")
                _, key_type = await get_owner_api_key_for_provider(state.get("owner_id") if state else None, prov_for_key, return_source=True)
            except Exception:
                key_type = "platform-key"

            # Same numbers, kept locally for the health event's per-node breakdown.
            from agent.utils.node_metrics import record_node_seconds
            record_node_seconds(
                state, "check_pandas", execution_time, provider=provider, model=model_name,
                input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=tokens_used,
                key_type=key_type,
            )

            await tracker.record_event(
                owner_id=state.get("owner_id") if state else None,
                agent_id=state.get("agent_id") if state else None,
                operation="llm_call",
                label="pandas_agent_routing",
                session_id=state.get("session_id") if state else None,
                request_id=state.get("request_id") if state else None,
                operation_id="check_pandas_needed",
                key_type=key_type,
                metadata=metadata,
                metrics=[
                    {"name": "input_tokens", "value": float(input_tokens or 0)},
                    {"name": "output_tokens", "value": float(output_tokens or 0)},
                    {"name": "total_tokens", "value": float(tokens_used)},
                    {"name": "duration_ms", "value": duration_ms},
                ],
            )
        except Exception as e:
            logger.warning(f"[USAGE TRACKING] Failed to record check_pandas_needed LLM event: {e}")

        if needs_pandas:
            return "invoke_pandas"
        else:
            return "final_answer_node"

    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.error(f"Error in check_pandas_needed: {e}")

        # Fallback heuristic: keyword + size based decision to avoid blocking the flow
        fallback_query = (query or "").lower()
        keywords = _ANALYSIS_KEYWORDS

        result_count = 0
        try:
            if isinstance(db_result, (list, tuple)):
                result_count = len(db_result)
            else:
                result_count = 1
        except Exception:
            result_count = 0

        keyword_match = any(k in fallback_query for k in keywords)
        if keyword_match or result_count > 50:
            logger.info("Pandas fallback: invoking pandas agent based on heuristic")
            return "invoke_pandas"
        else:
            logger.info("Pandas fallback: skipping pandas agent based on heuristic")
            return "final_answer_node"
