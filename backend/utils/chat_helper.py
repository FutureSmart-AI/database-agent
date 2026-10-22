from typing import Optional, List, Dict, Any
import time
import json
import uuid
import traceback
from logger import logger
from agent.db_utils.session_db_utils import (
    get_past_conversation
)
from agent.db_utils.session_db_utils import log_new_session
from agent.db_utils.common_db_utils import upload_to_db_nl2sql_logs
from agent.runner import run_agent_flow
from agent.utils.follow_up import generate_follow_up_questions
from agent.utils.common_utils import serialize_db_result


async def get_past_messages_safe(session_id: str, user_id: str, agent_id: str, user_query: str) -> Dict[str, Any]:
    """
    Wrapper around get_past_messages to handle session creation and message retrieval safely
    """
    try:
        if not session_id or session_id in ["", "string"]:
            logger.info("No valid session_id provided. Creating a new session...")
            session_info = await log_new_session(user_id, agent_id, user_query)
            return {"past_messages": [], "session_id": session_info['session_id']}
        else:
            logger.info(f"Getting history for session {session_id}")
            past_messages = await get_past_conversation(session_id)
            return {"past_messages": past_messages, "session_id": session_id}
    except Exception as e:
        logger.error(f"Error in get_past_messages_safe: {str(e)}")
        traceback.print_exc()
        return {"past_messages": [], "session_id": session_id}


async def prepare_chat_response(
    agent_id: str, 
    body: Any, 
    user_id: str, 
    owner_email: str, 
    past_messages: List[Dict], 
    session_id: str, 
    request_id: str,
    chat_id: str,
    runtime_db: Dict,
    db_fetch_elapsed: float
) -> Dict[str, Any]:
    """Core logic to run the agent flow and prepare a non-streaming response"""
    agent_start_time = time.time()
    
    result = await run_agent_flow(
        query=body.query,
        past_messages=past_messages,
        table_descriptions=None,
        runtime_db_details=runtime_db,
        selected_tables=None,
        few_shot_examples=None,
        user_id=user_id,
        owner_id=owner_email,
        agent_id=agent_id,
        allowed_graphs=body.allowed_charts,
        include_graph_output=bool(body.chart_output),
        session_id=session_id,
        request_id=request_id,
    )

    agent_elapsed = time.time() - agent_start_time
    final_text = result.get("response", "")
    
    # Optional follow-up question generation
    follow_up_questions = None
    if getattr(body, "follow_up", False):
        try:
            follow_up_questions = await generate_follow_up_questions(
                owner_id=owner_email,
                agent_id=agent_id,
                messages=past_messages,
                refined_query=result.get("refined_query", body.query),
                response=final_text,
                follow_up_context=None,
            )
        except Exception as fu_err:
            logger.error(f"Follow-up generation failed: {fu_err}")

    # Persist logs
    chart_output_payload = format_chart_output_payload(result, bool(body.chart_output))
    await upload_to_db_nl2sql_logs(
        session_id, user_id, agent_id, chat_id, body.query,
        result.get("refined_query", body.query), result.get("sql_query", ""),
        result.get("db_result", []), final_text, chart_output_payload,
        agent_elapsed, db_fetch_elapsed, result.get("total_tokens", 0),
        bool(body.chart_output), bool(body.debug_info)
    )

    # Build final response
    final_response = {
        "response": final_text,
        "session_id": session_id,
        "chat_id": chat_id,
        "follow_up": follow_up_questions,
        "debug_info": format_debug_info(result, body) if body.debug_info else None,
        "chart_output": format_chart_output(result) if body.chart_output else None
    }
    
    return final_response


def format_chart_output_payload(result: Dict, chart_output: bool) -> Optional[str]:
    """Format chart JSON for database logging"""
    if not chart_output:
        return None
        
    graph_json = result.get("graph_json")
    if graph_json and (graph_json.get("graph_suggestion") or graph_json.get("graph_data") or graph_json.get("metadata")):
        return json.dumps(graph_json)
    else:
        return json.dumps({"post_processing_query": result.get("post_processing_query")})


def format_debug_info(result: Dict, body: Any) -> Dict[str, Any]:
    """Format debug information for the response"""
    return {
        "query": body.query,
        "refined_query": result.get("refined_query", body.query),
        "sql_query": result.get("sql_query", ""),
        "db_result": serialize_db_result(result.get("db_result", [])),
        "selected_tables": result.get("selected_tables")
    }


def format_chart_output(result: Dict) -> Optional[Dict[str, Any]]:
    """Format chart output for the response"""
    graph_json = result.get("graph_json")
    if graph_json and (graph_json.get("graph_suggestion") or graph_json.get("graph_data") or graph_json.get("metadata")):
        return {
            "chart_suggestion": graph_json.get("graph_suggestion"),
            "chart_data": graph_json.get("graph_data"),
            "metadata": graph_json.get("metadata"),
        }
    return None


async def agent_stream_generator(
    agent_id: str,
    body: Any,
    user_id: str,
    owner_email: str,
    past_messages: List[Dict],
    session_id: str,
    request_id: str,
    chat_id: str,
    runtime_db: Dict,
    db_fetch_elapsed: float
):
    """Generator for streaming chat responses"""
    try:
        agent_start_time = time.time()
        
        result = await run_agent_flow(
            query=body.query,
            past_messages=past_messages,
            table_descriptions=None,
            runtime_db_details=runtime_db,
            selected_tables=None,
            few_shot_examples=None,
            user_id=user_id,
            owner_id=owner_email,
            agent_id=agent_id,
            allowed_graphs=body.allowed_charts,
            include_graph_output=bool(body.chart_output),
            session_id=session_id,
            request_id=request_id,
        )
        
        agent_elapsed = time.time() - agent_start_time
        final_text = result.get("response", "")
        
        # Follow-up generation
        follow_up_questions = None
        if getattr(body, "follow_up", False):
            try:
                follow_up_questions = await generate_follow_up_questions(
                    owner_id=owner_email,
                    agent_id=agent_id,
                    messages=past_messages,
                    refined_query=result.get("refined_query", body.query),
                    response=final_text,
                    follow_up_context=None,
                )
            except Exception as fu_err:
                logger.error(f"Follow-up generation failed: {fu_err}")

        # Stream chunks (sentences)
        for sentence in filter(None, [s.strip() for s in final_text.split('.')]):
            yield f"data: {json.dumps({'chunk': sentence + '.', 'session_id': session_id})}\n\n"

        # Persist logs
        chart_output_payload = format_chart_output_payload(result, bool(body.chart_output))
        await upload_to_db_nl2sql_logs(
            session_id, user_id, agent_id, chat_id, body.query,
            result.get("refined_query", body.query), result.get("sql_query", ""),
            result.get("db_result", []), final_text, chart_output_payload,
            agent_elapsed, db_fetch_elapsed, result.get("total_tokens", 0),
            bool(body.chart_output), bool(body.debug_info)
        )

        # Send final metadata
        final_response = {
            "response": final_text,
            "session_id": session_id,
            "chat_id": chat_id,
            "follow_up": follow_up_questions,
            "debug_info": format_debug_info(result, body) if body.debug_info else None,
            "chart_output": format_chart_output(result) if body.chart_output else None
        }
        yield f"full_metadata: {json.dumps(final_response)}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {str(e)}")
        traceback.print_exc()
        yield f"full_metadata: {json.dumps({'error': str(e)})}\n\n"
