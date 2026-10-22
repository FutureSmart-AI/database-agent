"""
Pandas Agent as a LangGraph subgraph.
This agent handles CSV data transformation using pandas operations.
"""

from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
from logger import logger
from pandas_agent.node import (
    PandasAgentState,
    tool_node,
    planning_node,
    validation_node,
    execution_node,
    validation_decision,
    execution_decision,
)

# Build the graph
def create_pandas_agent_graph():
    """Create the Pandas agent graph."""
    logger.info("Creating Pandas agent graph")
    workflow = StateGraph(PandasAgentState)
    
    # Add nodes
    workflow.add_node("planning_node", planning_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("execute", execution_node)

    # Add edges and entry point
    workflow.set_entry_point("planning_node")

    # After planning -> always go directly to validation
    workflow.add_edge("planning_node", "validation")

    # Validation -> execute on success, or back to planning on validation error
    workflow.add_conditional_edges(
        "validation",
        validation_decision,
        {
            "execute": "execute",
            "planning": "planning_node",
        }
    )

    # Execution -> end on success, or back to planning on execution error
    workflow.add_conditional_edges(
        "execute",
        execution_decision,
        {
            "planning": "planning_node",
            "end": END,
        }
    )
    logger.info("Pandas agent graph created successfully")
    
    return workflow.compile()


# Create the compiled graph
pandas_agent_graph = create_pandas_agent_graph()
