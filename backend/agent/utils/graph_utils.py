import json
from agent.utils.prompts import get_post_processing_prompt
import logging
from dotenv import load_dotenv
import os
load_dotenv()
logger = logging.getLogger(__name__)
    
from pydantic import BaseModel
from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from typing import List, Dict, Any, Optional


from langsmith import traceable
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs
@traceable
async def post_processor(db_results, post_processing_query, graph_suggestion, supported_graph_types):
    
    try:
        # Get the system role prompt using the new format
        system_role = get_post_processing_prompt(db_results, post_processing_query, graph_suggestion, supported_graph_types)
        
        from agent.utils.model_profiles import operation_config, build_chat_model
        llm = build_chat_model(operation_config("sql_agent.post_processing"))
            # Define the Pydantic model for structured output
        # class PostProcessorOutput(BaseModel):
        #     graph_suggestion: str
        #     graph_data: List[Dict[str, Any]]  # List of key-value pairs describing the graph data
        from services.pydantic_models import PostProcessorOutput
        structured_llm = llm.with_structured_output(PostProcessorOutput)
        
        prompt = ChatPromptTemplate.from_messages(
            [("system", system_role)]
        )
        # Send the prompt to the structured LLM
        chain = prompt | structured_llm
        response = await chain.ainvoke({})
        logger.info(f"Results of post_processor chain: {response}")
        
        # Access the structured response fields
        graph_suggestion = response.graph_suggestion
        graph_data = response.graph_data
        # logging.info(f"Results of post_processor chain, graph_data: {graph_data}")
        
        return graph_suggestion, graph_data
    except Exception as e:
        logger.error(f"Error in post_processor: {e}")
        return None, None
