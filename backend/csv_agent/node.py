from agent.utils.model_profiles import response_text
from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError
from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
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
import pandas as pd
import io
import os
import operator
from pandas_agent.graph import pandas_agent_graph
from logger import logger
from dotenv import load_dotenv


load_dotenv()
from csv_agent.utils.model_config_loader import load_model_config
from agent.utils.owner_credential_utils import get_llm_api_key, get_provider_from_model
from otel_tracing import track_time
from agent.utils.openai_chat_kwargs import plain_completion_chat_kwargs

# State definition for CSV Agent
class CSVAgentState(TypedDict):
    """State for the CSV agent workflow."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    csv_path: str
    query: str
    generate_answer: bool
    owner_id: str | None
    dataframe_result: dict | None
    answer: str | None
    error: str | None


# Node functions
@track_time("Node: CSV Agent - Invoke Pandas Agent")
async def invoke_pandas_agent(state: CSVAgentState) -> CSVAgentState:
    """
    Invoke the Pandas agent subgraph.
    This node handles the transformation of state to/from the subgraph.
    """
    logger.info(f"Invoking Pandas agent - Query: {state['query'][:100]}")
    
    # Transform parent state to subgraph state
    subgraph_input = {
        "messages": [HumanMessage(content=state["query"])],
        "csv_path": state["csv_path"],
        "query": state["query"],
        "chart_type": None,  # CSV agent doesn't need chart type
        "owner_id": state.get("owner_id"),
        "plan": None,
        "execution_result": None,
        "error": None,
        "retry_count": 0  # Initialize retry counter
    }
    
    # Invoke the subgraph
    try:
        logger.info(f"Invoking pandas_agent_graph with input: {subgraph_input}")
        subgraph_result = await pandas_agent_graph.ainvoke(subgraph_input)
        logger.info(f"Pandas agent invocation completed. Subgraph result: {subgraph_result}")
    except Exception as e:
        logger.error(f"Pandas agent invocation failed: {str(e)}")
        return {
            **state,
            "error": f"Pandas agent error: {str(e)}",
            "messages": state["messages"] + [AIMessage(content=f"Error: {str(e)}")]
        }
    
    # Check for errors in subgraph result
    if subgraph_result.get("error"):
        logger.error(f"Pandas agent error: {subgraph_result['error'][:100]}")
        return {
            **state,
            "error": subgraph_result["error"],
            "messages": state["messages"] + [AIMessage(content=f"Error: {subgraph_result['error']}")]
        }
    
    # Extract execution result
    execution_result = subgraph_result.get("execution_result")
    if not execution_result:
        logger.error("No execution result from Pandas agent")
        return {
            **state,
            "error": "No execution result from Pandas agent",
            "messages": state["messages"] + [AIMessage(content="Error: No result from Pandas agent")]
        }
    
    # Parse the execution result to extract DataFrame
    df_data_string = None
    
    # Try to extract CSV block first
    if "CSV_DATA_START" in execution_result:
        try:
            start = execution_result.index("CSV_DATA_START") + len("CSV_DATA_START")
            end = execution_result.index("CSV_DATA_END", start)
            csv_text = execution_result[start:end].strip()
            df = pd.read_csv(io.StringIO(csv_text))
            logger.info(f"CSV block extracted successfully. Shape: {df.shape}")
        except Exception as e:
            # Fallback to legacy parsing
            logger.debug(f"CSV block extraction failed: {str(e)}, falling back to legacy parsing")
            df_data_string = execution_result
            df = pd.read_csv(io.StringIO(df_data_string), sep=r'\s{2,}', engine='python')
    else:
        # Legacy parsing
        logger.debug("No CSV block found, using legacy parsing")
        df_blocks = execution_result.split("\n" + "="*70 + "\n")
        if df_blocks:
            last_block = [b for b in df_blocks if b.strip()][-1]
            data_start = last_block.find("Data:")
            if data_start != -1:
                df_data_string = last_block[data_start + 5:].strip()
                summary_start = df_data_string.find("Summary Statistics:")
                if summary_start != -1:
                    df_data_string = df_data_string[:summary_start].strip()
                df = pd.read_csv(io.StringIO(df_data_string), sep=r'\s{2,}', engine='python')
    
    # Convert to dictionary format
    dataframe_dict = {
        "columns": df.columns.tolist(),
        "data": df.to_dict('records'),
        "shape": df.shape,
        "dtypes": df.dtypes.astype(str).to_dict()
    }
    logger.info(f"DataFrame processed. Rows: {df.shape[0]}, Columns: {df.shape[1]}")
    
    # Transform subgraph result back to parent state
    # Record usage event for Pandas agent step
    try:
        from agent.utils.usage_tracking import get_usage_tracker
        tracker = get_usage_tracker()
        owner_id = state.get("owner_id")
        token_metrics = subgraph_result.get("token_metrics") or {}
        input_tokens = token_metrics.get("input_tokens", 0)
        output_tokens = token_metrics.get("output_tokens", 0)
        total_tokens = token_metrics.get("total_tokens", 0)
        logger.info(
            f"Recording usage event for CSV agent: owner_id={owner_id}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, total_tokens={total_tokens}"
        )
        # execution_time is 0: the subgraph ran before this node, so its duration is not
        # available here. Previously this timed an empty block (start_time and the
        # subtraction with nothing in between), which recorded the same 0 while looking
        # like a measurement. Pass it explicitly rather than faking a timer.
        await tracker.record_llm_call(
            owner_id=owner_id,
            agent_id=None,
            operation="csv_pandas_agent",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            execution_time=0.0,
            extra_metrics=[],
        )
    except Exception as e:
        logger.error(f"Error sending usage event: {e}")
    return {
        **state,
        "dataframe_result": dataframe_dict,
        "messages": state["messages"] + [AIMessage(content="DataFrame processed successfully")]
    }


@track_time("Node: CSV Agent - Generate Answer")
async def generate_answer_node(state: CSVAgentState) -> CSVAgentState:
    """Generate a natural language answer from the DataFrame."""
    logger.info("Generating natural language answer")
    if not state.get("generate_answer"):
        logger.debug("Answer generation skipped (generate_answer=False)")
        return state
    
    if not state.get("dataframe_result"):
        logger.error("No DataFrame result to generate answer from")
        return {
            **state,
            "error": "No DataFrame result to generate answer from"
        }

    # Use repo-level model_config.json as the primary source for fallback model
    try:
        cfg = load_model_config()
    except Exception as e:
        logger.warning(f"Could not load model_config.json for CSV agent: {e}")
        cfg = {}

    answer_conf = operation_config("csv_agent.answer")
    fallback_model_name = answer_conf["model"]
    fallback_provider = answer_conf["provider"]
    logger.info(f"Using model for CSV answer generation: {fallback_model_name} (provider: {fallback_provider})")
    
    # Get API key for fallback model
    owner_id = state.get("owner_id")
    api_key = await get_llm_api_key(owner_id, fallback_model_name, fallback_provider)

    # Dynamically select the model class based on provider
    provider_lower = fallback_provider.lower()

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

    ModelClass = configured_model_factory(answer_conf)

    openai_kwargs = (
        plain_completion_chat_kwargs(fallback_model_name)
        if provider_lower in ("openai", "azure_openai")
        else {}
    )

    llm = ModelClass(model=fallback_model_name, temperature=0, api_key=api_key, **openai_kwargs) if api_key else ModelClass(model=fallback_model_name, temperature=0, **openai_kwargs)
    
    df_dict = state["dataframe_result"]
    df_string = f"Columns: {df_dict['columns']}\nData: {df_dict['data']}"
    
    prompt = f"""Based on the following processed data, provide a concise and direct answer to the user's query.
    
Query: {state['query']}

Processed Data:
{df_string}

Provide a clear, direct answer to the query based on the data."""
    
    response = await llm.ainvoke([
        SystemMessage(content="You are a data analyst providing direct answers based on processed data."),
        HumanMessage(content=prompt)
    ])
    
    logger.info("Answer generated successfully")
    return {
        **state,
        "answer": response_text(response),
        "messages": state["messages"] + [AIMessage(content=response_text(response))]
    }


def should_generate_answer(state: CSVAgentState) -> str:
    """Decide whether to generate an answer."""
    if state.get("error"):
        logger.warning("Error detected, skipping answer generation")
        return "end"
    if state.get("generate_answer"):
        logger.info("Proceeding to answer generation")
        return "generate_answer"
    logger.debug("Answer generation not requested")
    return "end"
