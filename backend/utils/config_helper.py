import os
import traceback
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from logger import logger
from chatbot_management.db_utils.chatbot_node_db_utils import (
    get_node_configs_from_db,
    upsert_node_configs_in_db,
    delete_node_config_from_db
)
from chatbot_management.db_utils.chatbot_params_db_utils import (
    get_chatbot_details_by_agent_id,
    update_chatbot_details_by_agent_id
)

# Valid LangGraph node names from the actual implementation (agent/runner.py)
VALID_NODE_NAMES = [
    "router",              # Refines user query and suggests graph types
    "sql_gen",             # Generates SQL query from natural language
    "final_answer_node",   # Generates final natural language answer
    "chart_agent"      # Generates chart JSON output
]

# Node configuration mapping - maps node names to their actual implementation details from the codebase
NODE_CONFIG_MAP = {
    "router": {
        "default_provider": "groq",
        "default_model": "openai/gpt-oss-120b",
        "default_temperature": 0.0,
        "uses_llm": True,
        "description": "Refines and clarifies the user's natural language query to ensure it can be accurately converted to SQL",
        "prompt": """Given the following user "Query" and "CONVERSATION LOG", formulate a "Refined Query" and a "Post Processing Query" that would be the most relevant to provided "Query". If no conversation log is available, set "Refined Query" same as the "Query".

The "Refined Query" is a query that is specifically tailored to extracting the information and the "Post Processing Query" is a query that focuses on displaying the information in graph format based on the Human's Query.

If provided with a conversation log, check whether the Human's Query is referencing any prior conversations by examining their previous queries. If there is no reference, correct the grammar in the Human's query and return it as the refined version.

Ensure that the refined query is always in English.

Strictly ensure that the refined query does not contain the SQL query, it should always be the refined user query free from references to graphs and charts.

You should understand the user_query and decide which graph is most suitable. If a graph can be made for the user query, always suggest the graph based on the supported graphs. Even if the query doesn't explicitly mention a particular graph, you should be able to deduce the required graph for the query. Always suggest a suitable graph type that can be used to visualise the user query results.

If user mentions anything regarding graphs or charts, create a "Post Processing Query" which is a query to formulate a question to generate a graph or chart depending on the user query. If the user doesn't explicitly mention anything about the graphs or charts, deduce the required graph or chart that is suitable for the user query and create a "Post Processing Query".

When refining the query, ensure that no context related to plotting graphs or charts is included in the "refined_query". Instead, retain only the core query logic related to data retrieval and analysis. Any instructions or requests for plotting graphs, charts, or visualizations should be exclusively included in the "post_processing_query", as it is specifically designed to handle such tasks.

Supported Graphs: Bar, Pie, Line, Histogram, Bubble"""
    },
    "sql_gen": {
        "default_provider": "groq",
        "default_model": "openai/gpt-oss-120b",
        "default_temperature": 0.0,
        "uses_llm": True,
        "description": "Generates accurate SQL queries based on the natural language input and database schema",
        "prompt": """Instructions:
- You are a SQL expert. Given an input question, create a syntactically correct SQL query to run. Unless otherwise specified.
- For text/varchar columns: Use ILIKE (PostgreSQL) or LIKE (MySQL) for case-insensitive matching. This handles both partial matches and case variations.
- For enum types (e.g., payment_status, order_status): Use = operator with UPPERCASE values for exact matches (e.g., WHERE payment_status = 'FAILED').
- For UUID types: Use = operator for exact matches.
- IMPORTANT: Unless you know the exact case-sensitive value, prefer ILIKE (PostgreSQL) or LIKE (MySQL) for text columns to ensure matches regardless of case.
- You can order the results by a relevant column to return the most interesting examples in the database.
- Pay attention to use only the column names that you can see in the schema description. Be careful to not query for columns that do not exist. Also, pay attention to which column is in which table.

Restriction:
- Strictly use the table names provided to generate the query. Don't use any other table names.
- DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database.
- Unless the user specifies a specific number of examples they wish to obtain, always limit your query to at most 10 results.

The user query may often be broad or vague and may not exactly match the names, attributes, or terms present in the database. Your goal is to first refine the query by aligning it with the provided list of actual terms or values that exist in the database. This refinement ensures that the query retrieves the most accurate and relevant data. Always verify and match the spelling and terminology of these terms against the list to ensure consistency."""
    },
    "final_answer_node": {
        "default_provider": "groq",
        "default_model": "openai/gpt-oss-120b",
        "default_temperature": 0.0,
        "uses_llm": True,
        "description": "Formats the SQL results into a user-friendly natural language response",
        "prompt": """Given the following user question, corresponding SQL query, SQL result and user info, please answer the user question.

Please follow these guidelines:
1. Provide responses in natural language only - no code, ASCII art, or visualizations
2. Only use the information from the provided SQL result to answer the question
3. If the SQL query references any tables that are not in the explicitly allowed tables list, respond with: "I'm sorry, I don't have information about that. The requested data source is restricted or not available."
4. For Database-Unrelated User question:
   - If the User question is a greeting (like "Hello") you can answer like "Hello, how can I help you today?"
   - If the User question is asking about capabilities, services, or what you can do (e.g., "What can you do?", "What services do you offer?", "How can you help me?"), explain that your main role is to answer questions related to the connected database. Include this statement: "I can help you explore and query data from the database I'm connected to. Here is a list of available tables:"
5. If the SQL query is valid and uses allowed tables, but doesn't match the user's question, still provide an answer based on the SQL result, explaining what data is actually being shown."""
    },
    "chart_agent": {
        "default_provider": "groq",
        "default_model": "openai/gpt-oss-120b",
        "default_temperature": 0.0,
        "uses_llm": True,
        "description": "Generates JSON configuration for data visualization graphs based on query results",
        "prompt": """Generate accurate and intuitive chart configurations. Prioritize choosing the most appropriate visualization based on user intent and data, and map data columns clearly to chart elements in a renderable JSON format."""
    }
}

async def get_agent_config_data(user_id: str, agent_id: str, fields: Optional[str] = None, node_name: Optional[str] = None) -> Dict[str, Any]:
    """Fetch agent configuration including nodes and agent parameters"""
    try:
        # Get agent details from DB utility
        agent = await get_chatbot_details_by_agent_id(agent_id)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Get node configurations from DB utility
        nodes = await get_node_configs_from_db(agent_id, node_name)

        # Build nodes list
        nodes_list = []
        existing_nodes = {node.node_name: node for node in nodes}

        # Determine which nodes to return
        if node_name:
            if node_name in existing_nodes:
                nodes_to_return = [node_name]
            elif node_name in VALID_NODE_NAMES:
                nodes_to_return = [node_name]
            else:
                nodes_to_return = []
        else:
            all_custom_nodes = set(existing_nodes.keys())
            all_standard_nodes = set(VALID_NODE_NAMES)
            nodes_to_return = list(all_standard_nodes | all_custom_nodes)

        # Return configurations for the selected nodes
        for node_name_item in nodes_to_return:
            if node_name_item in ("select_and_fewshots", "sql_exec"):
                continue
            if node_name_item in existing_nodes:
                node = existing_nodes[node_name_item]
                nodes_list.append({
                    "node_name": node.node_name,
                    "provider": node.provider,
                    "model": node.model,
                    "temperature": node.temperature,
                    "is_default": node.is_default,
                    "prompt": node.prompt
                })
            else:
                node_config = NODE_CONFIG_MAP.get(node_name_item, {})
                if node_config.get("uses_llm"):
                    nodes_list.append({
                        "node_name": node_name_item,
                        "provider": node_config.get("default_provider", "openai"),
                        "model": node_config.get("default_model", "gpt-5-mini"),
                        "temperature": node_config.get("default_temperature", 0.0),
                        "is_default": True,
                        "prompt": node_config.get("prompt", node_config.get("description", f"Default prompt for {node_name_item} node"))
                    })
                else:
                    nodes_list.append({
                        "node_name": node_name_item,
                        "provider": None,
                        "model": None,
                        "temperature": None,
                        "is_default": True,
                        "prompt": node_config.get("prompt", node_config.get("description", f"Node {node_name_item} does not use LLM"))
                    })

        supported_graphs_env = os.getenv("SUPPORTED_GRAPHS", "Bar, Pie, Line, Histogram, Bubble")
        allowed_graphs = [g.strip().lower() for g in supported_graphs_env.split(",")]
        if getattr(agent, "allowed_graphs", None):
            try:
                if isinstance(agent.allowed_graphs, list):
                    allowed_graphs = [str(g).strip().lower() for g in agent.allowed_graphs]
                elif isinstance(agent.allowed_graphs, str):
                    allowed_graphs = [g.strip().lower() for g in agent.allowed_graphs.split(",")]
            except Exception:
                pass

        agent_params = {
            "agent_name": agent.chatbot_name,
            "system_prompt": agent.system_prompt,
            "service_description": getattr(agent, "service_description", None) or "NL2SQL converts natural language questions into SQL, executes them against the connected database, and returns clear answers with optional chart visualizations. It refines queries, generates schema-aware SQL, supports data transformations via pandas, and can produce charts through the chart agent. It operates only on the databases connected to this agent.",
            "greet_message": agent.greet_message,
            "debug_info": agent.debug_info if agent.debug_info is not None else False,
            "chart_output": agent.graph_output if agent.graph_output is not None else True,
            "allowed_graphs": allowed_graphs,
            "max_query_execution_time": agent.max_query_execution_time if agent.max_query_execution_time is not None else 30,
            "enable_query_caching": agent.enable_query_caching if agent.enable_query_caching is not None else True
        }

        config = {
            "nodes": nodes_list,
            "agent_params": agent_params
        }

        if fields:
            field_list = [f.strip() for f in fields.split(",")]
            filtered_config = {f: config[f] for f in field_list if f in config}
            config = filtered_config

        return {
            "agent_id": agent_id,
            "config": config
        }
    except Exception as e:
        logger.error(f"Error in get_agent_config_data: {str(e)}")
        raise

async def upsert_agent_node_configs(agent_id: str, body: Any) -> Dict[str, Any]:
    """Upsert node configurations for an agent"""
    try:
        # Validate node names
        for config in body.configs:
            if config.node_name not in VALID_NODE_NAMES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid node_name '{config.node_name}'. Must be one of: {', '.join(VALID_NODE_NAMES)}"
                )

        # Verify agent exists
        agent = await get_chatbot_details_by_agent_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Use DB utility to upsert node configs
        updated = await upsert_node_configs_in_db(agent_id, body.configs)
        return {"updated": updated}
    except Exception as e:
        logger.error(f"Error in upsert_agent_node_configs: {str(e)}")
        raise

async def patch_agent_config_params(agent_id: str, body: Any, auth_type: str, current_user_id: Optional[str] = None) -> Dict[str, Any]:
    """Partially update agent parameters"""
    try:
        # Prepare update data
        update_data = {
            "agent_name": body.agent_name,
            "system_prompt": body.system_prompt,
            "service_description": body.service_description,
            "greet_message": body.greet_message,
            "debug_info": body.debug_info,
            "graph_output": body.chart_output,
            "allowed_graphs": body.allowed_graphs,
            "max_query_execution_time": body.max_query_execution_time,
            "enable_query_caching": body.enable_query_caching
        }
        
        # Use DB utility to update chatbot details
        agent = await update_chatbot_details_by_agent_id(
            agent_id, 
            update_data, 
            owner_id=current_user_id if auth_type == "session" else None
        )

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found or you don't have access")

        return {
            "agent_id": agent_id,
            "agent_params": {
                "agent_name": agent.chatbot_name,
                "system_prompt": agent.system_prompt,
                "service_description": getattr(agent, "service_description", None),
                "greet_message": agent.greet_message,
                "debug_info": agent.debug_info if agent.debug_info is not None else False,
                "graph_output": agent.graph_output if agent.graph_output is not None else True,
                "allowed_graphs": agent.allowed_graphs if getattr(agent, "allowed_graphs", None) is not None else ["bar", "line", "pie"],
                "max_query_execution_time": agent.max_query_execution_time if agent.max_query_execution_time is not None else 30,
                "enable_query_caching": agent.enable_query_caching if agent.enable_query_caching is not None else True
            },
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error in patch_agent_config_params: {str(e)}")
        raise

async def reset_node_to_default(agent_id: str, node_name: str) -> Dict[str, Any]:
    """Delete a node configuration to reset to default"""
    try:
        if node_name not in VALID_NODE_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node_name '{node_name}'. Must be one of: {', '.join(VALID_NODE_NAMES)}"
            )

        # Verify agent exists
        agent = await get_chatbot_details_by_agent_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Use DB utility to delete node config
        deleted = await delete_node_config_from_db(agent_id, node_name)

        if not deleted:
            return {
                "message": f"Node {node_name} is already using default configuration"
            }

        return {
            "message": f"Node {node_name} has been reset to default configuration."
        }
    except Exception as e:
        logger.error(f"Error in reset_node_to_default: {str(e)}")
        raise
