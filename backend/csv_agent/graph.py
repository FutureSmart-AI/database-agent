"""
CSV Agent as a LangGraph workflow.
Uses Pandas Agent as a subgraph to process CSV queries.
"""

from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
import pandas as pd
from logger import logger
from csv_agent.node import CSVAgentState,invoke_pandas_agent,generate_answer_node,should_generate_answer


# Build the graph with Pandas agent as subgraph
def create_csv_agent_graph():
    """Create the CSV agent graph with Pandas agent as subgraph."""
    logger.info("Creating CSV agent graph")
    workflow = StateGraph(CSVAgentState)
    
    # Add nodes
    workflow.add_node("invoke_pandas_agent", invoke_pandas_agent)
    workflow.add_node("generate_answer", generate_answer_node)
    
    # Add edges
    workflow.set_entry_point("invoke_pandas_agent")
    workflow.add_conditional_edges(
        "invoke_pandas_agent",
        should_generate_answer,
        {
            "generate_answer": "generate_answer",
            "end": END
        }
    )
    workflow.add_edge("generate_answer", END)
    logger.info("CSV agent graph created successfully")
    
    return workflow.compile()


# Create the compiled graph
csv_agent_graph = create_csv_agent_graph()


# Helper function to invoke the CSV agent
async def process_csv_query(csv_path: str, query: str, generate_answer: bool = False, owner_id: str | None = None) -> dict:
    """
    Process a CSV query using the CSV agent graph.
    
    Args:
        csv_path: Path to the CSV file
        query: Natural language query
        generate_answer: Whether to generate a natural language answer
        
    Returns:
        Dict with dataframe_result and optional answer
    """
    logger.info(f"Processing CSV query: {query[:100]}, Generate answer: {generate_answer}")
    initial_state = {
        "messages": [],
        "csv_path": csv_path,
        "query": query,
        "generate_answer": generate_answer,
        "owner_id": owner_id,
        "dataframe_result": None,
        "answer": None,
        "error": None
    }
    
    result = await csv_agent_graph.ainvoke(initial_state)
    
    if result.get("error"):
        logger.error(f"CSV query processing failed: {result['error'][:100]}")
        raise Exception(result["error"])
    
    logger.info("CSV query processing completed successfully")
    return {
        "dataframe": result["dataframe_result"],
        "answer": result.get("answer")
    }
