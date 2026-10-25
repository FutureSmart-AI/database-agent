"""Retry helper for DeepSeek structured (json_mode) LLM calls.

DeepSeek V4 (`deepseek-v4-flash`) intermittently returns an EMPTY completion for
`with_structured_output(..., method="json_mode")` calls. An empty body has no JSON
to parse, so LangChain raises `OutputParserException('Invalid json output: ')`
(see the LangSmith traces). The empties are rare and transient — re-invoking almost
always returns valid JSON — so we retry a couple of times before giving up. Later
attempts nudge the temperature up to break the (unlikely) case where a specific
input is *deterministically* empty at temp 0.

This helper is a no-op for every other provider: only the DeepSeek call sites route
through it, and it simply re-raises the final exception after exhausting retries, so
each caller's existing graceful-fallback (except block) still handles the terminal
case exactly as before.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import ValidationError

try:
    from langchain_core.exceptions import OutputParserException
except ImportError:  # pragma: no cover - very old langchain
    class OutputParserException(Exception):
        pass

# Retryable = the empty/malformed-JSON failure mode. Provider 400s / timeouts are NOT
# retried here (they are not the empty-output problem) — callers handle those as today.
_RETRYABLE = (OutputParserException, ValidationError)


async def ainvoke_structured_with_retry(
    make_chain: Callable[[float], Any],
    inputs: Any,
    *,
    base_temp: float = 0.0,
    logger: Any = None,
    label: str = "",
) -> Any:
    """Invoke a DeepSeek structured chain, retrying on empty-output / parse failure.

    Args:
        make_chain: factory ``make_chain(temperature) -> runnable`` that builds the
            ``prompt | llm.with_structured_output(...)`` chain at the given temperature.
            Rebuilt per attempt so later attempts can use a bumped temperature.
        inputs: the value passed to ``chain.ainvoke(inputs)``.
        base_temp: the configured temperature (used for the first attempt).
        logger: optional logger for retry breadcrumbs.
        label: node name for log lines (e.g. "router").

    Returns:
        The chain's result on the first successful attempt.

    Raises:
        The last ``OutputParserException`` / ``ValidationError`` if every attempt fails,
        so the caller's existing except-block degrades gracefully as before.
    """
    # First attempt at the configured temperature, then escalate to break a
    # deterministic-empty response. De-dupe so we don't waste an attempt on the same temp.
    temps = [base_temp]
    for bump in (0.4, 0.7):
        t = max(base_temp, bump)
        if t not in temps:
            temps.append(t)

    last_err: Exception | None = None
    for i, temp in enumerate(temps):
        try:
            return await make_chain(temp).ainvoke(inputs)
        except _RETRYABLE as err:
            last_err = err
            if logger is not None:
                if i + 1 < len(temps):
                    logger.warning(
                        "[deepseek-retry] %s attempt %d/%d empty/parse failure (%s) — retrying at temp=%.2f",
                        label, i + 1, len(temps), type(err).__name__, temps[i + 1],
                    )
                else:
                    logger.warning(
                        "[deepseek-retry] %s exhausted %d attempts (%s) — degrading to fallback",
                        label, len(temps), type(err).__name__,
                    )
    raise last_err  # type: ignore[misc]
