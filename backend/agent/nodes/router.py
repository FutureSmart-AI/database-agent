from __future__ import annotations

import os
import json
import logging
import time
import asyncio
from typing import Literal, Optional, Any, Dict,TypedDict
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv

from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
from langchain_community.callbacks import get_openai_callback
from langchain_core.prompts import ChatPromptTemplate
from langsmith import traceable

try:
    from langchain_core.exceptions import OutputParserException
except ImportError:
    class OutputParserException(Exception):
        pass

from agent.utils.agent_config_loader import get_agent_node_config, merge_agent_config_with_defaults
from agent.utils.model_config_loader import load_model_config
from agent.utils.model_profiles import operation_config, configured_model_factory
from agent.utils.prompts import get_router_prompt, get_node_additional_instruction, ensure_json_directive
from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model, get_openai_compatible_base_url
from agent.utils.common_utils import get_conversation_string
from agent.state import AgentState
from logger import logger
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.node_metrics import record_node_seconds
from agent.utils.deepseek_retry import ainvoke_structured_with_retry
from otel_tracing import track_time

load_dotenv()

# Moved imports to top level for performance
try:
    from langchain_groq import ChatGroq
except ImportError:
    ChatGroq = None

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None

try:
    from groq import RateLimitError as GroqRateLimitError
except ImportError:
    GroqRateLimitError = Exception

# 400s from the provider (e.g. Groq strict tool-schema rejecting a null field, or a
# malformed request) are NOT rate limits/timeouts — catch them separately so a bad
# structured-output validation degrades gracefully instead of bubbling up as a 500.
_BAD_REQUEST_ERRORS: tuple = ()
try:
    from groq import BadRequestError as _GroqBadRequestError
    _BAD_REQUEST_ERRORS += (_GroqBadRequestError,)
except ImportError:
    pass
try:
    from openai import BadRequestError as _OpenAIBadRequestError
    _BAD_REQUEST_ERRORS += (_OpenAIBadRequestError,)
except ImportError:
    pass

# Provider connection/timeout errors (groq.APIConnectionError, openai.APITimeoutError, …) are
# NOT Python's builtin ConnectionError/TimeoutError, so the service handler must name them
# explicitly — otherwise a transient network blip to the LLM surfaces as a raw 500.
_SERVICE_ERRORS: tuple = (GroqRateLimitError, TimeoutError, ConnectionError, asyncio.TimeoutError)
try:
    from groq import APIConnectionError as _GroqConnErr, APITimeoutError as _GroqTimeoutErr
    _SERVICE_ERRORS += (_GroqConnErr, _GroqTimeoutErr)
except ImportError:
    pass
try:
    from openai import APIConnectionError as _OAIConnErr, APITimeoutError as _OAITimeoutErr
    _SERVICE_ERRORS += (_OAIConnErr, _OAITimeoutErr)
except ImportError:
    pass



class RouterOutput(TypedDict):
    """Router decision with refined queries for downstream nodes."""
    
    action: Literal["END", "sql_gen_node"]
    """Route decision: END for direct response, sql_gen_node for database queries"""
    
    refined_query: str
    """Clean data query without visualization language, with history resolved. Used by SQL generation."""

    visualization_query: str
    """Query with visualization context and history resolved, for the graph node.
    Empty string "" when no chart/graph/plot is requested. Never null."""

    response: str
    """Direct response text when action=END; empty string "" otherwise. Never null."""


@traceable(run_type="chain", name="node_router")
async def node_router(state: AgentState) -> AgentState:
    """Router node that determines query routing and refines queries for downstream processing."""
    logger.info(
        "[WF] step.start=router | request_id=%s | session_id=%s",
        state.get("request_id"),
        state.get("session_id"),
    )
    supported_graphs = os.getenv("SUPPORTED_GRAPHS")

    # Load router config from model_config.json
    CONFIG = load_model_config()
    router_conf = CONFIG["sql_agent"]["router"]

    # Load node-specific config from database and merge with defaults
    agent_id = state.get("agent_id")
    owner_id = state.get("owner_id")

    # Fetch configuration and additional instructions in parallel
    node_conf_task = get_agent_node_config(agent_id, "router")
    extra_instr_task = get_node_additional_instruction(agent_id, "router")
    
    node_config, extra = await asyncio.gather(node_conf_task, extra_instr_task)

    router_conf = operation_config("router", node_config)

    model_name = router_conf["model"]
    provider = router_conf["provider"]
    temperature = router_conf.get("temperature", 0.0)

    try:
        _prev = extra if extra and len(extra) <= 1000 else (extra[:1000] + "..." if extra else "")
        logger.info(f"Router node additional_instruction text_preview={_prev}")
    except Exception:
        pass
    # Conversation history present → include follow-up/context-inheritance rules; on a first
    # turn those blocks are dead weight, so gate them out.
    has_history = bool(state.get("past_messages"))
    prompt: ChatPromptTemplate = get_router_prompt(supported_graphs, extra, has_history=has_history)

    # Get API keys with logging - use the return_source version to avoid double calls later
    logger.info(f"🤖 [LLM_CALL] Router node | owner_id: {owner_id} | model: {model_name}")
    api_key, key_type = await get_owner_api_key_for_provider(owner_id, provider, return_source=True)
    
    # Log which credential source is being used
    if api_key:
        logger.info(f"🚀 [LLM_CALL] Router node initialized | owner_id: {owner_id} | model: {model_name} | source: {key_type}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] Router node using default env credentials | owner_id: {owner_id} | model: {model_name}")

    # Dynamically select the model class based on provider
    provider_lower = provider.lower()
    base_url = get_openai_compatible_base_url(provider_lower)  # deepseek/minimax → ChatOpenAI+base_url
    is_groq = False

    if provider_lower == "groq":
        if ChatGroq is None:
            logger.error("ChatGroq not available but provider is groq")
            return {**state, "error": "ChatGroq not available"}
        ModelClass = ChatGroq
        is_groq = True
    elif provider_lower == "anthropic":
        if ChatAnthropic is None:
            logger.error("ChatAnthropic not available but provider is anthropic")
            return {**state, "error": "ChatAnthropic not available"}
        ModelClass = ChatAnthropic
    elif provider_lower in ("google", "gemini"):
        if ChatGoogleGenerativeAI is None:
            logger.error("ChatGoogleGenerativeAI not available but provider is google")
            return {**state, "error": "ChatGoogleGenerativeAI not available"}
        ModelClass = ChatGoogleGenerativeAI
    else:
        ModelClass = ChatOpenAI

    # Choose structured output style based on provider
    ModelClass = configured_model_factory(router_conf)

    openai_kwargs = (
        structured_tool_chat_kwargs(model_name)
        if provider_lower in ("openai", "azure_openai")
        else {}
    )
    if base_url:  # deepseek / minimax → OpenAI-compatible endpoint
        openai_kwargs = {**openai_kwargs, "base_url": base_url}
        if provider_lower == "deepseek":  # V4 defaults to slow thinking mode — disable it
            openai_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    if is_groq:
        # Groq's default structured mode (strict json_schema) rejects a null value for an
        # Optional field like `visualization_query` with a 400, crashing the request. Use
        # function_calling instead (non-strict) — matches db_router.py / sql_gen.py.
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key).with_structured_output(RouterOutput, method="function_calling") if api_key else ModelClass(model=model_name, temperature=temperature).with_structured_output(RouterOutput, method="function_calling")
    elif provider_lower == "deepseek":
        # DeepSeek V4 is a thinking model: rejects function_calling tool_choice — use json_mode.
        # json_mode requires the literal word "json" in the prompt, which the router prompt lacks.
        prompt = ensure_json_directive(prompt)
        def _make_deepseek_chain(_t: float):
            # Rebuilt per retry attempt so ainvoke_structured_with_retry can bump temperature
            # when DeepSeek returns an empty completion (see agent/utils/deepseek_retry.py).
            _llm = (ModelClass(model=model_name, temperature=_t, api_key=api_key, **openai_kwargs)
                    if api_key else ModelClass(model=model_name, temperature=_t, **openai_kwargs))
            return prompt | _llm.with_structured_output(RouterOutput, method="json_mode")
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key, **openai_kwargs).with_structured_output(RouterOutput, method="json_mode") if api_key else ModelClass(model=model_name, temperature=temperature, **openai_kwargs).with_structured_output(RouterOutput, method="json_mode")
    elif provider_lower == "google":
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key).with_structured_output(RouterOutput) if api_key else ModelClass(model=model_name, temperature=temperature).with_structured_output(RouterOutput)
    else:
        model = ModelClass(model=model_name, temperature=temperature, api_key=api_key, **openai_kwargs).with_structured_output(RouterOutput, method="function_calling") if api_key else ModelClass(model=model_name, temperature=temperature, **openai_kwargs).with_structured_output(RouterOutput, method="function_calling")

    # Include both user and assistant turns so the router can resolve references to
    # values, segments, or labels that only appeared in the bot's previous answer.
    # Only the last few turns are needed for reference resolution — older history
    # adds no value and inflates the prompt for long sessions.
    _MAX_RECENT_TURNS = 3        # how many back-and-forth exchanges to keep
    _MAX_ASSISTANT_CHARS = 800   # cap long markdown tables / data dumps

    past = state.get("past_messages", []) or []
    recent = past[-(_MAX_RECENT_TURNS * 2):]  # at most 6 messages

    router_history = []
    for m in recent:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "assistant" and len(content) > _MAX_ASSISTANT_CHARS:
            content = content[:_MAX_ASSISTANT_CHARS] + "\n...[truncated]"
        router_history.append({"role": role, "content": content})
    messages = get_conversation_string(router_history)
    start_time = time.time()

    invoke_inputs = {
        "messages": messages,
        "query": state["query"],
        "supported_graphs": supported_graphs,
    }

    router_failure_mode: Optional[str] = None
    try:
        with get_openai_callback() as cb:
            if provider_lower == "deepseek":
                # DeepSeek occasionally returns an empty json_mode completion → retry before degrading.
                resp = await ainvoke_structured_with_retry(
                    _make_deepseek_chain, invoke_inputs,
                    base_temp=temperature, logger=logger, label="router",
                )
            else:
                resp = await (prompt | model).ainvoke(invoke_inputs)
    except (OutputParserException, ValidationError) as parse_err:
        router_failure_mode = "parse"
        logger.warning(
            "[WF] router.parse_failure | request_id=%s | session_id=%s | err_type=%s | query_preview=%s",
            state.get("request_id"),
            state.get("session_id"),
            type(parse_err).__name__,
            (state.get("query") or "")[:200],
        )
        resp = RouterOutput(
            action="END",
            refined_query=state["query"],
            visualization_query="",
            response="I had trouble understanding that question. Could you rephrase it?",
        )
        state["is_answered"] = False
    except _SERVICE_ERRORS as svc_err:
        router_failure_mode = "service"
        logger.error(
            "[WF] router.service_failure | request_id=%s | session_id=%s | err_type=%s | err=%s",
            state.get("request_id"),
            state.get("session_id"),
            type(svc_err).__name__,
            str(svc_err)[:500],
        )
        resp = RouterOutput(
            action="END",
            refined_query=state["query"],
            visualization_query="",
            response="The service is temporarily busy. Please try again in a moment.",
        )
        state["is_answered"] = False
    except _BAD_REQUEST_ERRORS as bad_req:
        # Provider rejected the structured-output request (e.g. Groq strict-schema null).
        # Degrade to a safe END instead of letting it surface as a 500.
        router_failure_mode = "bad_request"
        logger.error(
            "[WF] router.bad_request | request_id=%s | session_id=%s | err_type=%s | err=%s",
            state.get("request_id"),
            state.get("session_id"),
            type(bad_req).__name__,
            str(bad_req)[:500],
        )
        resp = RouterOutput(
            action="END",
            refined_query=state["query"],
            visualization_query="",
            response="I had trouble understanding that question. Could you rephrase it?",
        )
        state["is_answered"] = False

    execution_time = time.time() - start_time
    tokens_used = 0 if router_failure_mode else getattr(cb, "total_tokens", 0)
    input_tokens = None if router_failure_mode else getattr(cb, "prompt_tokens", None)
    output_tokens = None if router_failure_mode else getattr(cb, "completion_tokens", None)
    
    # Accumulate token usage in state
    state["total_tokens"] = state.get("total_tokens", 0) + tokens_used

    # Keep the same numbers locally for the health event's per-node breakdown.
    record_node_seconds(
        state, "router", execution_time, provider=provider, model=model_name,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=tokens_used,
        key_type=key_type, errors=1 if router_failure_mode else 0,
    )

    # Record usage event (non-blocking)
    try:
        tracker = get_usage_tracker()
        k_type = key_type or "platform-key"
        
        # Fire and forget
        await tracker.record_event(
            owner_id=state.get("owner_id"),
            agent_id=state.get("agent_id"),
            operation="llm_call",
            label="supervisor_routing",
            session_id=state.get("session_id"),
            request_id=state.get("request_id"),
            operation_id="router",
            key_type=k_type,
            metadata={"provider": provider, "model": model_name, "temperature": temperature},
            metrics=[
                {"name": "input_tokens", "value": float(input_tokens or 0)},
                {"name": "output_tokens", "value": float(output_tokens or 0)},
                {"name": "total_tokens", "value": float(tokens_used)},
                {"name": "duration_ms", "value": float(execution_time * 1000.0)},
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to record router usage event (non-blocking): {e}")
    
    d = dict(resp) if not isinstance(resp, dict) else resp
    
    # Update state with router outputs.
    # Default to END (not sql_gen_node) on missing action so a partially malformed
    # response cannot fail-open into the SQL generation pipeline.
    state.update(
        action=d.get("action", "END"),
        refined_query=d.get("refined_query", state["query"]),
        visualization_query=d.get("visualization_query"),
        response=d.get("response")
    )
    
    logger.info(
        "[WF] step.end=router | request_id=%s | action=%s | exec_time=%.2fs",
        state.get("request_id"),
        state.get("action"),
        execution_time
    )
    
    return state


