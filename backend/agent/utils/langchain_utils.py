from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool as QuerySQLDatabaseTool
import asyncio
# from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.callbacks import get_openai_callback
from langsmith import traceable


from operator import itemgetter
from agent.utils.prompts import get_table_prompt, get_sql_query_prompt, get_answer_prompt
from agent.utils.common_utils import get_conversation_string

from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import PromptTemplate

from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

from pydantic import BaseModel, Field
import re
import logging
import time

from agent.db_utils.session_db_utils import get_past_conversation,log_new_session
logger = logging.getLogger(__name__)
import os
# from dotenv import load_dotenv
# load_dotenv()
# Rely on main.py or central config loader
from agent.db_utils import table_description_db_utils
import json
from agent.utils.model_config_loader import load_model_config
from agent.utils.model_profiles import operation_config, build_chat_model, ModelConfigurationError
from otel_tracing import track_time

from typing import List


# @st.cache_data
async def get_table_details(table_description_dict):
    # Parse the JSON-like string into a list of dictionaries
    table_names = []
    table_details = ""

    # Iterate over the list to extract table names and descriptions
    for key, value in table_description_dict.items():
        table_names.append(key)
        table_details += f"Table Name: {key}\nTable Description: {value}\n\n"

    return table_names, table_details


def get_table_selection_chain(node_conf=None):
    # Per-agent node override (chatbot_node_config) wins; else global model_config.json.
    config = load_model_config()
    select_table_config = operation_config("select_table", node_conf)

    provider = select_table_config.get("provider", "groq").lower()
    model_name = select_table_config.get("model")
    temperature = select_table_config.get("temperature", 0.0)
    
    logger.info(f"Using {provider} model for table selection: {model_name}")
    
    table_details_prompt = get_table_prompt()
    class TableSelectionChainOutput(BaseModel):
        selected_tables: List[str]
    
    llm = build_chat_model(select_table_config)

    # DeepSeek V4 thinking model → json_mode (function_calling tool_choice rejected).
    if provider == "deepseek":
        # json_mode requires the literal word "json" in the prompt.
        from agent.utils.prompts import ensure_json_directive
        table_details_prompt = ensure_json_directive(table_details_prompt)
        structured_llm = llm.with_structured_output(TableSelectionChainOutput, method="json_mode")
    elif provider in ("openai", "groq", "minimax"):
        structured_llm = llm.with_structured_output(TableSelectionChainOutput, method="function_calling")
    else:
        structured_llm = llm.with_structured_output(TableSelectionChainOutput)
    chain = table_details_prompt | structured_llm
    return chain

@traceable
@track_time("API: Select Tables")
async def select_tables(refined_query, table_description, node_conf=None):
    table_description = json.loads(table_description)
    logger.info(f"Table description: {table_description}")
    table_description_dict = {}
    for table in table_description:
        key = list(table.keys())[0]
        value = table[key]
        table_description_dict[key] = value
    logger.info(f"Table description dict: {table_description_dict}")
    
    table_names, table_details = await get_table_details(table_description_dict)
    
    try:
        table_selection_chain = get_table_selection_chain(node_conf)
        response = await table_selection_chain.ainvoke({
            "question": refined_query,
            "table_details": table_details
        })
        selected_tables = response.selected_tables
    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.warning(f"Structured table selection failed: {e}. Attempting manual extraction from response text if available.")
        # If the error contains the failed generation, try to extract table names from it
        selected_tables = []
        error_str = str(e)
        
        # Look for table names in the error message if it's a tool_use_failed error
        if "failed_generation" in error_str:
            for table_name in table_names:
                if f"- {table_name}" in error_str or f"'{table_name}'" in error_str or f"\"{table_name}\"" in error_str:
                    selected_tables.append(table_name)
        
        # If still empty, use all tables as a fallback to avoid failing the whole request
        if not selected_tables:
            logger.info("Manual extraction failed or no tables found. Falling back to all available tables.")
            selected_tables = table_names
            
    logger.info(f"Selected tables: {selected_tables} for query: {refined_query}")
    
    table_descriptions_str = ""
    for table in selected_tables:
        if table in table_description_dict:
            table_descriptions_str += f"Table Name: {table}, Table Description: {table_description_dict[table]}\n"
        
    return table_descriptions_str, selected_tables

@track_time("API: Get Table Descriptions and Selected Tables")
async def get_table_descriptions_and_selected_tables(query, db_details, user_id, agent_id, db_id=None):
    table_descriptions = {}
    selected_tables = []

    start_time = time.time()

    # Fetch table descriptions and DB table names in parallel
    db_desc_task = table_description_db_utils.list_table_description_from_db(user_id, agent_id, db_id=db_id)
    db_tables_task = asyncio.to_thread(table_description_db_utils.get_table_names_from_db, db_details)
    
    db_response, db_table_names = await asyncio.gather(db_desc_task, db_tables_task)
    
    # Safely extract fields when db_response can be None or missing keys
    record = (db_response or {}).get("record")
    descriptions = getattr(record, "description", None) if record else None
    table_flags = getattr(record, "entry_flags", None) if record else None

    # Match table descriptions with the actual tables in the database
    if descriptions:
        # Handle both dict (from JSON column auto-deserialize) and string formats
        if isinstance(descriptions, str):
            table_descriptions = json.loads(descriptions)
        else:
            table_descriptions = descriptions

        if isinstance(table_flags, str):
            table_flags = json.loads(table_flags)
        elif table_flags is None:
            table_flags = {}
        matched_tables = table_description_db_utils.match_table_names_with_db(table_flags, table_descriptions, db_table_names)
        # If nothing matches, fallback to all DB tables
        if matched_tables:
            table_descriptions, selected_tables = await select_tables(query, json.dumps(matched_tables))
        else:
            logging.info(f"No table matches found from descriptions/flags. Falling back to all DB tables.")
            selected_tables = db_table_names
    else:
        # Fallback if no descriptions found
        selected_tables = db_table_names

    end_time = time.time()
    logger.info(f"Table selection in {end_time - start_time} seconds.")

    return table_descriptions, selected_tables