from agent.utils.model_profiles import response_text
"""Run a report's optional analysis prompt over the finished run.

When a report defines `analysis_prompt`, the executor calls this once after every query has
finished and stores the result as the run's `overall_summary`. It is a **qualitative** summary
of what the answers say — not a verdict on whether the agent did well; per-query scoring is a
separate concern this feature deliberately leaves out.

The model only ever sees the transcript, and is told not to add anything that isn't in it: an
invented figure in a summary of database answers would be indistinguishable from a real one.
"""
from typing import Any, Dict, List, Optional

from logger import logger

from batch_query_reports import reports_env

_SYSTEM_PROMPT = (
    "You are summarizing the output of a batch query report run against a database agent. "
    "Follow the user's instructions and produce a clear, qualitative summary. "
    "Use ONLY the questions and answers in the transcript — never invent figures, "
    "table names, or findings that are not present in it. If the transcript is missing "
    "something the instructions ask for, say so plainly."
)


def build_transcript(group_results: List[Dict[str, Any]]) -> str:
    """Flatten `[{group_id, type, results:[{question, answer, error}]}]` into readable text.

    Truncated to a character budget: a report with large result tables in its answers can
    otherwise exceed the model's context, and a summary of the first N queries is far more
    useful than a failed call.
    """
    out: List[str] = []
    for g in group_results:
        out.append(f"### Group ({g.get('type', 'independent')})")
        for r in g.get("results", []):
            question = (r.get("question") or "").strip()
            error = r.get("error")
            if error:
                out.append(f"Q: {question}\nERROR: {error}\n")
            else:
                out.append(f"Q: {question}\nA: {(r.get('answer') or '').strip()}\n")

    text = "\n".join(out)
    limit = reports_env.REPORTS_ANALYSIS_MAX_TRANSCRIPT_CHARS
    if len(text) > limit:
        text = text[:limit] + "\n…[transcript truncated]"
    return text


async def run_analysis(
    analysis_prompt: str,
    group_results: List[Dict[str, Any]],
) -> Optional[str]:
    """Return the analysis summary, or None if it could not be generated.

    Never raises: a run whose queries all succeeded must still be reported as completed if only
    the summary failed, so the caller treats None as "no summary" and moves on.
    """
    transcript = build_transcript(group_results)
    if not transcript.strip():
        logger.warning("[reports.analysis] empty transcript — skipping analysis")
        return None

    from agent.utils.model_profiles import operation_config, build_chat_model
    conf = operation_config("reports.analysis")
    model_name = conf["model"]
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = build_chat_model(conf)
        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"INSTRUCTIONS:\n{analysis_prompt}\n\n"
                f"REPORT TRANSCRIPT:\n{transcript}"
            )),
        ])
        summary = response_text(response)
        if not summary:
            logger.warning(f"[reports.analysis] model {model_name} returned an empty summary")
            return None
        return summary
    except Exception as e:
        logger.error(f"[reports.analysis] model {model_name} failed: {e}", exc_info=True)
        return None
