"""OpenAI endpoint and reasoning compatibility for product model calls.

When using ``/v1/chat/completions``, OpenAI rejects ``reasoning_effort`` together with
function/tool calls — including LangChain structured output via
``with_structured_output(..., method="function_calling")``. Some GPT-5.x models
(e.g. gpt-5.4-mini) default to a low-enough effort that simply omitting the kwarg
avoids the conflict. Newer ones (e.g. gpt-5.6-luna) apply a non-"none" reasoning
effort by default even when it isn't passed, so omitting it is not enough — the
kwarg must be sent explicitly as "none" (see :func:`structured_tool_chat_kwargs`).

Plain message completions without tools may still use ``reasoning_effort``.
"""

from __future__ import annotations

from typing import Any


def structured_tool_chat_kwargs(model_name: str | None) -> dict[str, Any]:
    """Kwargs for ChatOpenAI when binding structured output that uses function/tools."""
    if model_name == "gpt-6.1-sol":
        return {"reasoning_effort": "low", "use_responses_api": True, "store": False}
    if model_name == "gpt-6-luna":
        return {"reasoning_effort": "none"}
    if model_name and "gpt-5" in model_name.lower():
        return {"reasoning_effort": "none"}
    return {}


def plain_completion_chat_kwargs(model_name: str | None) -> dict[str, Any]:
    """Kwargs for ChatOpenAI plain completions (no tool/function structured binding)."""
    if model_name in {"gpt-6.1-sol", "gpt-6-luna"}:
        return structured_tool_chat_kwargs(model_name)
    kwargs: dict[str, Any] = {}
    if model_name and "gpt-5" in model_name.lower():
        kwargs["reasoning_effort"] = "low"
    return kwargs


def product_chat_openai(**kwargs: Any):
    """Build the supported OpenAI clients without changing legacy providers.

    Some product operations construct a plain client before binding a schema,
    so compatibility must also apply there, rather than only at tool helpers.
    Responses is stateless; stored agent instructions/output schemas are retained.
    """
    from langchain_openai import ChatOpenAI

    model = kwargs.get("model") or kwargs.get("model_name")
    if model in {"gpt-6.1-sol", "gpt-6-luna"}:
        kwargs.update(structured_tool_chat_kwargs(model))
        if model == "gpt-6.1-sol":
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
            kwargs.pop("logprobs", None)
            kwargs.pop("top_logprobs", None)
            if kwargs.get("include"):
                kwargs["include"] = [item for item in kwargs["include"]
                                     if item != "message.output_text.logprobs"]
        kwargs.setdefault("timeout", 45)
        kwargs.setdefault("max_retries", 0)
        kwargs.setdefault("max_tokens", 8192 if model == "gpt-6.1-sol" else 2048)
    return ChatOpenAI(**kwargs)
