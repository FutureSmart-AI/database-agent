from __future__ import annotations
from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError

from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

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

from langsmith import traceable

from agent.utils.model_config_loader import load_model_config
from agent.utils.owner_credential_utils import get_llm_api_key, get_provider_from_model, get_openai_compatible_base_url
from logger import logger
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs


class FollowUpResponse(BaseModel):
    follow_up: List[str] = Field(
        ...,
        description="List of exactly two short follow-up questions.",
    )


def _build_followup_prompt(has_context: bool, *, groq_json_mode: bool = False) -> ChatPromptTemplate:
    """
    Build the follow-up question prompt.

    Mirrors the sample you provided:
    - Exactly 2 short follow-up questions
    - Prefer context if available, otherwise use conversation history
    """
    system_instructions = (
        "You predict the next two questions a user is most likely to ask the data assistant after the "
        "conversation shown below.\n\n"
        "**Voice — write as the user, not as the assistant:**\n"
        "- Phrase each follow-up as a real question (What / How / Why / Which / When / Where / Is / Are / Do / Did).\n"
        "- Do NOT use commands ('Show…', 'List…', 'Filter…', 'Group by…', 'Sort…'). Those are instructions, not questions.\n"
        "- Do NOT address the user ('Would you like…', 'Do you want…', 'Should we…'). Those are assistant-style prompts.\n\n"
        "**Answerability — the agent must be able to answer it from its own data:**\n"
        "- Every follow-up must be answerable by querying the database this agent is connected to. "
        "Use the entities, columns, metrics, and time ranges that ALREADY APPEAR in the conversation as your only source of grounding.\n"
        "- Do NOT invent topics, tables, or metrics that are not represented in the assistant's prior answer or in the user's prior questions.\n"
        "- Prefer drill-downs (a narrower slice of the same data), comparisons (over time, across categories), "
        "or breakdowns (by a dimension visible in the prior answer).\n\n"
        "**Content:**\n"
        "- Be specific to the data and entities in the prior exchange — no generic phrases ('Tell me more', 'Anything else?').\n"
        "- Keep each question under 15 words.\n"
        "- Don't repeat the question the user just asked.\n"
    )

    if has_context:
        system_instructions += (
            "\n**Context grounding:**\n"
            "The assistant's answer above may be truncated. Use the [Context] below (the SQL that "
            "ran and the data it returned) as the source of truth for what data is available. Only "
            "generate questions answerable from this context.\n"
            "Do NOT ask for information the assistant's last answer already states — ask the natural "
            "NEXT question (a drill-down, comparison, or breakdown over the entities shown).\n"
            "Phrase questions in plain business language — never mention SQL syntax, WHERE clauses, "
            "or internal column/table names verbatim.\n\n"
            "[Context]:\n{context}"
        )
    else:
        system_instructions += (
            "\nGround your questions in the values, columns, and entities that appear in the conversation history below — "
            "those are the only data points the agent can speak to."
        )

    # Groq (and OpenAI json_object) require the word "json" to appear in the messages
    # when response_format is json_object — see check_pandas.py for the same pattern.
    if groq_json_mode:
        system_instructions += (
            '\n\nIMPORTANT: Return a JSON object only, with key "follow_up" (array of exactly two strings).'
        )

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_instructions),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )


@traceable(run_type="chain", name="Follow-up Questions")
async def generate_follow_up_questions(
    *,
    owner_id: Optional[str],
    agent_id: Optional[str],
    messages: List[Dict[str, Any]],
    refined_query: str,
    response: str,
    follow_up_context: Optional[str] = None,
) -> List[str]:
    """
    Generate exactly two short follow-up questions for the given exchange.

    - Uses sql_agent.follow_up_questions in model_config.json (then fallback block, then defaults).
    - Uses owner-specific credentials when available, with env fallback.
    - Never raises to callers; on failure returns safe default questions.
    """
    try:
        # Build history: keep only the last 3 turns to avoid token exhaustion
        _MAX_TURNS = 3
        _MAX_ASSISTANT_CHARS = 800
        _MAX_USER_CHARS = 2000

        past = list(messages or [])
        past = past[-(_MAX_TURNS * 2):]  # at most 6 messages

        history = []
        for m in past:
            role = (m.get("role") or "").lower()
            content = m.get("content") or ""
            if role == "assistant" and len(content) > _MAX_ASSISTANT_CHARS:
                content = content[:_MAX_ASSISTANT_CHARS] + "\n...[truncated]"
            elif role == "user" and len(content) > _MAX_USER_CHARS:
                content = content[:_MAX_USER_CHARS] + "\n...[truncated]"
            history.append({"role": role, "content": content})

        # Append the current exchange. The CURRENT answer gets a much higher cap than history
        # messages: follow-ups must not re-ask what this answer already states, and with the old
        # 800-char cap long tabular answers lost their summary/conclusion — making the model
        # generate redundant questions (measured). History stays tightly capped.
        _MAX_CURRENT_ANSWER_CHARS = 2500
        history.append({"role": "user", "content": refined_query})
        history.append({"role": "assistant", "content": response[:_MAX_CURRENT_ANSWER_CHARS]})

        follow_cfg = operation_config("sql_agent.follow_up_questions")
        model_name, provider = follow_cfg["model"], follow_cfg["provider"]
        temperature = follow_cfg.get("temperature")

        provider_lower = (provider or "").lower()

        # Select model class based on provider
        if provider_lower == "groq":
            if ChatGroq is None:
                logger.error("Follow-up: ChatGroq not available but provider is groq")
                raise RuntimeError("Groq provider not available")
            ModelClass = ChatGroq
            is_groq = True
        elif provider_lower == "anthropic":
            if ChatAnthropic is None:
                logger.error("Follow-up: ChatAnthropic not available but provider is anthropic")
                raise RuntimeError("Anthropic provider not available")
            ModelClass = ChatAnthropic
            is_groq = False
        elif provider_lower in {"google", "gemini"}:
            if ChatGoogleGenerativeAI is None:
                logger.error("Follow-up: ChatGoogleGenerativeAI not available but provider is google/gemini")
                raise RuntimeError("Google provider not available")
            ModelClass = ChatGoogleGenerativeAI
            is_groq = False
        else:
            ModelClass = ChatOpenAI
            is_groq = False

        ModelClass = configured_model_factory(follow_cfg)

        # Resolve API key for this owner/model
        api_key = await get_llm_api_key(owner_id, model_name, provider)

        # Structured output configuration
        # Groq: use json_mode to avoid "Tool choice is required" errors when the model
        # outputs conversational text instead of calling the structured output tool.
        if is_groq:
            llm = (
                ModelClass(model=model_name, temperature=temperature, api_key=api_key).with_structured_output(
                    FollowUpResponse, method="json_mode"
                )
                if api_key
                else ModelClass(model=model_name, temperature=temperature).with_structured_output(
                    FollowUpResponse, method="json_mode"
                )
            )
        elif provider_lower in {"google", "gemini"}:
            llm = (
                ModelClass(model=model_name, temperature=temperature, api_key=api_key).with_structured_output(
                    FollowUpResponse
                )
                if api_key
                else ModelClass(model=model_name, temperature=temperature).with_structured_output(FollowUpResponse)
            )
        else:
            # OpenAI, or OpenAI-compatible (deepseek/minimax) via base_url (+ thinking off / json_mode for deepseek)
            openai_kwargs = (
                structured_tool_chat_kwargs(model_name)
                if provider_lower in ("openai", "azure_openai")
                else {}
            )
            _base = get_openai_compatible_base_url(provider_lower)
            if _base:
                openai_kwargs = {**openai_kwargs, "base_url": _base}
                if provider_lower == "deepseek":
                    openai_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            _method = "json_mode" if provider_lower == "deepseek" else "function_calling"

            llm = (
                ModelClass(model=model_name, temperature=temperature, api_key=api_key, **openai_kwargs).with_structured_output(
                    FollowUpResponse, method=_method
                )
                if api_key
                else ModelClass(model=model_name, temperature=temperature, **openai_kwargs).with_structured_output(
                    FollowUpResponse, method=_method
                )
            )

        has_context = bool(follow_up_context and follow_up_context.strip())
        # DeepSeek uses json_mode too, which (like Groq) requires the word "json" in the prompt.
        prompt = _build_followup_prompt(has_context=has_context, groq_json_mode=(is_groq or provider_lower == "deepseek"))

        invoke_payload: Dict[str, Any] = {"messages": history}
        if has_context:
            invoke_payload["context"] = follow_up_context

        logger.info(
            f"Generating follow-up questions | agent_id={agent_id} "
            f"provider={provider} model={model_name} has_context={has_context}"
        )

        result: FollowUpResponse = await (prompt | llm).ainvoke(invoke_payload)
        # Return whatever the model produced (cap at 2). No fallback — empty if
        # the model produced nothing usable; the frontend decides whether to show.
        questions = [q for q in (result.follow_up or []) if isinstance(q, str) and q.strip()]
        return questions[:2]
    except Exception as e:
        logger.error(f"Failed to generate follow-up questions: {e}")
        return []



