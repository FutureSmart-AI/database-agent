"""Render a run as Markdown, JSON or CSV.

Exports are generated on demand from the persisted run (`db_utils.get_run_full`) and are never
stored — there is nothing to invalidate when a late result lands, and no second copy of the
data to keep in step.

The three formats answer three different needs: JSON is the full fidelity payload for
integrations, Markdown is what a person reads or pastes into a doc, CSV is one row per query
for a spreadsheet.
"""
import csv
import io
import json
from typing import Any, Dict, List

# Cap rendered table rows so a query returning tens of thousands of rows cannot turn a report
# into an unopenable Markdown file. The complete data stays available in the JSON export.
_MAX_TABLE_ROWS = 50


def to_json(run: Dict[str, Any]) -> str:
    return json.dumps(run, indent=2, ensure_ascii=False, default=str)


# --- execution details -------------------------------------------------------

def _cell(value: Any) -> str:
    """Stringify a db_result cell for Markdown, escaping what would break the table."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _column_names(columns: Any) -> List[str]:
    """Column labels. The chat endpoint sends `[{"name": …, "type": …}]`; plain strings are
    also accepted so a simpler producer still renders."""
    names: List[str] = []
    for c in columns or []:
        if isinstance(c, dict):
            names.append(str(c.get("name") or c.get("column") or ""))
        else:
            names.append(str(c))
    return names


def _row_cells(row: Any, names: List[str]) -> List[Any]:
    """Cells in column order. Rows arrive as objects keyed by column name; positional lists
    are also accepted."""
    if isinstance(row, dict):
        return [row.get(n) for n in names]
    if isinstance(row, (list, tuple)):
        return list(row)
    return [row]


def _render_db_result(db_result: Any) -> List[str]:
    """Render `{columns, rows, row_count, truncated}` as a Markdown table."""
    if not isinstance(db_result, dict):
        return []
    names = _column_names(db_result.get("columns"))
    rows = db_result.get("rows") or []
    if not names:
        return []

    lines = [
        "| " + " | ".join(_cell(n) for n in names) + " |",
        "| " + " | ".join("---" for _ in names) + " |",
    ]
    for row in rows[:_MAX_TABLE_ROWS]:
        lines.append("| " + " | ".join(_cell(c) for c in _row_cells(row, names)) + " |")
    lines.append("")

    # `row_count` is the true total when the payload itself was already truncated upstream.
    total = db_result.get("row_count")
    total = total if isinstance(total, int) and total >= len(rows) else len(rows)
    if len(rows) > _MAX_TABLE_ROWS or total > len(rows) or db_result.get("truncated"):
        lines += [f"_Showing {min(len(rows), _MAX_TABLE_ROWS)} of {total} rows._", ""]
    return lines


def _render_execution_details(details: Any) -> List[str]:
    """Markdown block for one query's execution trace. Empty when there is none."""
    if not isinstance(details, dict):
        return []

    lines: List[str] = []
    sql = details.get("sql_query")
    if sql:
        lines += ["**Executed SQL**", "", "```sql", str(sql).strip(), "```", ""]

    context = []
    if details.get("selected_db_name"):
        context.append(f"database `{details['selected_db_name']}`")
    if details.get("tables_used"):
        context.append(f"tables {', '.join(str(t) for t in details['tables_used'])}")
    if details.get("cross_db"):
        context.append("answered across multiple databases")
    if context:
        lines += ["_" + " · ".join(context) + "_", ""]

    lines += _render_db_result(details.get("db_result"))

    if details.get("chart_data"):
        suggestion = details.get("chart_suggestion")
        lines += [f"_Chart data available{f' ({suggestion})' if suggestion else ''}._", ""]
    if details.get("export_url"):
        lines += [f"_Full result export: {details['export_url']}_", ""]
    return lines


def to_markdown(run: Dict[str, Any]) -> str:
    s = run.get("summary", {})
    total_time = s.get("total_time_ms")
    lines = [
        f"# {run.get('name') or 'Report Run'}",
        "",
        f"- **Run ID:** {run.get('run_id')}",
        f"- **Report ID:** {run.get('report_id')}",
        f"- **Agent:** {run.get('agent_id')}",
        f"- **Status:** {run.get('status')}",
        f"- **Trigger:** {run.get('trigger')}",
        f"- **Executed at:** {run.get('executed_at')}",
        "",
        "## Summary",
        "",
        f"- Total queries: {s.get('total_queries', 0)}",
        f"- Completed: {s.get('completed_queries', 0)}",
        f"- Failed: {s.get('failed_queries', 0)}",
        f"- Total time: {total_time if total_time is not None else '—'} ms",
        f"- Avg response time: {s.get('avg_response_time_ms', 0)} ms",
        f"- Total tokens: {s.get('total_tokens', 0)}",
    ]
    if run.get("failure_reason"):
        lines += ["", f"> ⚠️ **Run failed:** {run['failure_reason']}"]
    if run.get("overall_summary"):
        lines += ["", "## Overall Analysis", "", run["overall_summary"]]

    for i, group in enumerate(run.get("query_groups", []), start=1):
        lines += ["", f"## Group {i} — {group.get('type')}", ""]
        if group.get("type") == "sequential" and group.get("conversation_flow"):
            lines += ["### Conversation flow", ""]
            for turn in group["conversation_flow"]:
                lines += [
                    f"**Q:** {turn.get('question')}",
                    "",
                    f"**A:** {turn.get('answer') or '_(no answer)_'}",
                    "",
                ]
        for r in group.get("results", []):
            lines += [f"### {r.get('question')}", ""]
            if r.get("error"):
                lines += [f"> ⚠️ **Error:** {r['error']}", ""]
            else:
                lines += [r.get("answer") or "_(no answer)_", ""]
            # Rendered for failed queries too: when a query fails, the SQL it attempted is
            # usually the most useful thing in the export.
            lines += _render_execution_details(r.get("execution_details"))
            meta = []
            if r.get("response_time_ms") is not None:
                meta.append(f"{r['response_time_ms']} ms")
            if r.get("token_usage") is not None:
                meta.append(f"{r['token_usage']} tokens")
            if r.get("is_answered") is False:
                meta.append("agent reported the question as unanswered")
            if meta:
                lines += ["_" + " · ".join(meta) + "_", ""]
    return "\n".join(lines)


def to_csv(run: Dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "group_type", "question", "answer", "is_answered",
        "sql_query", "tables_used", "database", "row_count",
        "response_time_ms", "token_usage", "session_id", "error",
    ])
    for group in run.get("query_groups", []):
        gtype = group.get("type")
        for r in group.get("results", []):
            details = r.get("execution_details")
            if not isinstance(details, dict):
                details = {}
            db_result = details.get("db_result")
            row_count = db_result.get("row_count") if isinstance(db_result, dict) else None
            writer.writerow([
                gtype,
                r.get("question") or "",
                r.get("answer") or "",
                "" if r.get("is_answered") is None else r["is_answered"],
                details.get("sql_query") or "",
                ", ".join(str(t) for t in (details.get("tables_used") or [])),
                details.get("selected_db_name") or "",
                "" if row_count is None else row_count,
                r.get("response_time_ms") if r.get("response_time_ms") is not None else "",
                r.get("token_usage") if r.get("token_usage") is not None else "",
                r.get("session_id") or "",
                r.get("error") or "",
            ])
    return buf.getvalue()


# format -> (renderer, media_type, file extension)
EXPORTERS = {
    "json": (to_json, "application/json", "json"),
    "md": (to_markdown, "text/markdown", "md"),
    "csv": (to_csv, "text/csv", "csv"),
}
