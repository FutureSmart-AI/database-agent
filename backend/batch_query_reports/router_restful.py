"""Public (user-facing) Batch Query Reports API.

Routes are agent-scoped under `/v1/agents/{agent_id}/reports`, matching the rest of NL2SQL —
`agent_id` in the path is what `require_agent_permission` resolves the caller's access from.
Full paths are `/nl2sql/api/v1/agents/{agent_id}/reports/...`.

A report belongs to an agent, and so does every run under it: each handler verifies the
report/run really sits inside the agent from the path before touching it, so a valid id from
another agent still returns 404.
"""
import traceback

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import Response

from agent.utils.authorization import require_agent_permission
from chatbot_management.utils.api_validation import get_api_key_or_session
from logger import logger

from batch_query_reports import db_utils
from batch_query_reports.executor import start_run
from batch_query_reports.exporters import EXPORTERS
from batch_query_reports.pydantic_models_restful import (
    CancelRunResponse,
    CreateReportRequest,
    CreateReportResponse,
    MessageResponse,
    ReportListResponse,
    ReportResponse,
    ReportSettingsResponse,
    RunCreatedResponse,
    RunListResponse,
    RunStatusResponse,
    UpdateReportRequest,
    UpdateReportSettingsRequest,
)
from batch_query_reports.schedule_utils import validate_cron

router = APIRouter(prefix="/v1")

# Sanity ceiling on the per-agent query cap, so a typo cannot effectively disable it.
_MAX_QUERIES_UPPER_BOUND = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_limit_message(limit: int) -> str:
    """User-facing limit message — no internal config names leak into it."""
    return (
        f"Report exceeds the maximum query limit ({limit}). "
        f"Reduce the number of queries or increase the configured limit."
    )


def _validate_query_groups(query_groups, limit: int) -> None:
    if not query_groups:
        raise HTTPException(status_code=400, detail="query_groups must contain at least one group")
    total_queries = 0
    for g in query_groups:
        if not g.queries:
            raise HTTPException(status_code=400, detail="Each query group must contain at least one query")
        if any(not (q or "").strip() for q in g.queries):
            raise HTTPException(status_code=400, detail="Queries cannot be empty")
        total_queries += len(g.queries)
    if total_queries > limit:
        raise HTTPException(status_code=400, detail=_query_limit_message(limit))


def _validate_schedule(schedule) -> None:
    if not schedule or schedule.frequency != "cron":
        return
    if not schedule.cron:
        raise HTTPException(
            status_code=400, detail="cron expression is required when frequency is 'cron'"
        )
    # Rejected at save time: an expression croniter cannot parse would otherwise be stored
    # happily and leave the report silently unscheduled.
    if not validate_cron(schedule.cron):
        raise HTTPException(
            status_code=400, detail=f"Invalid cron expression: {schedule.cron}"
        )


async def _verify_agent(agent_id: str) -> None:
    if not await db_utils.agent_exists(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


async def _verify_report_in_agent(report_id: str, agent_id: str) -> dict:
    """Fetch the report and confirm it belongs to the agent in the path."""
    report = await db_utils.get_report(report_id)
    if not report or report["agent_id"] != agent_id:
        raise HTTPException(status_code=404, detail="Report not found for this agent")
    return report


async def _verify_run_in_report(run_id: str, report_id: str, agent_id: str) -> dict:
    await _verify_report_in_agent(report_id, agent_id)
    status_obj = await db_utils.get_run_status(run_id)
    if not status_obj or status_obj["report_id"] != report_id or status_obj["agent_id"] != agent_id:
        raise HTTPException(status_code=404, detail="Run not found for this report")
    return status_obj


def _dump(model):
    return model.model_dump(exclude_unset=True) if hasattr(model, "model_dump") else model.dict(exclude_unset=True)


def _groups_to_dicts(query_groups):
    return [g.model_dump() if hasattr(g, "model_dump") else g.dict() for g in query_groups]


# ---------------------------------------------------------------------------
# Report definition
# ---------------------------------------------------------------------------

@router.post(
    "/agents/{agent_id}/reports",
    response_model=CreateReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    request: CreateReportRequest,
    agent_id: str = Path(..., description="Agent ID the report queries"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Create a report definition

    A report is a reusable template: its query groups, optional report-level instructions,
    optional analysis prompt and optional schedule. Nothing executes until a run is created —
    pass `run_immediately: true` to also start one now.
    """
    try:
        await _verify_agent(agent_id)

        limit = await db_utils.get_effective_query_limit(agent_id)
        _validate_query_groups(request.query_groups, limit)
        _validate_schedule(request.schedule)

        report_id = await db_utils.create_report(
            agent_id=agent_id,
            user_id=auth.get("user_id"),
            name=request.name,
            query_groups=_groups_to_dicts(request.query_groups),
            report_instructions=request.report_instructions,
            analysis_prompt=request.analysis_prompt,
            schedule=_dump(request.schedule) if request.schedule else None,
        )

        response = {"report_id": report_id}
        if request.run_immediately:
            run = await db_utils.create_run(
                report_id, trigger="manual", user_id=auth.get("user_id")
            )
            if run:
                await start_run(run["run_id"])
                response["run_id"] = run["run_id"]

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating report for agent {agent_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/reports", response_model=ReportListResponse)
async def list_reports(
    agent_id: str = Path(..., description="Agent ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """List the agent's report definitions, newest first."""
    try:
        await _verify_agent(agent_id)
        return {"reports": await db_utils.list_reports(agent_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing reports for agent {agent_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ---------------------------------------------------------------------------
# Settings — declared BEFORE /{report_id} so "settings" is not taken for a report id.
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}/reports/settings", response_model=ReportSettingsResponse)
async def get_report_settings(
    agent_id: str = Path(..., description="Agent ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    Get the agent's report settings

    Returns the effective per-report query cap plus the system default, so the UI never
    hardcodes a limit that can change server-side.
    """
    try:
        await _verify_agent(agent_id)
        return await db_utils.get_report_settings(agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting report settings for agent {agent_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/agents/{agent_id}/reports/settings", response_model=ReportSettingsResponse)
async def update_report_settings(
    request: UpdateReportSettingsRequest,
    agent_id: str = Path(..., description="Agent ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Set the agent's per-report query cap

    Every query in a report is a full agent run, so this is a cost control. It applies to new
    reports and to runs of existing ones alike — lowering it below an existing report's size
    blocks that report from running until it is trimmed.
    """
    value = request.max_queries_per_report
    if value < 1 or value > _MAX_QUERIES_UPPER_BOUND:
        raise HTTPException(
            status_code=400,
            detail=f"max_queries_per_report must be between 1 and {_MAX_QUERIES_UPPER_BOUND}.",
        )
    try:
        await _verify_agent(agent_id)
        return await db_utils.update_max_queries_per_report(
            agent_id, value, auth.get("user_id")
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating report settings for agent {agent_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """Get one report definition."""
    try:
        return await _verify_report_in_agent(report_id, agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting report {report_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/agents/{agent_id}/reports/{report_id}", response_model=MessageResponse)
async def update_report(
    request: UpdateReportRequest,
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Update a report definition

    Only the fields present in the body are written. `model_fields_set` is what lets an
    explicit `null` mean "clear this" — without it, `schedule: null` (remove the schedule)
    would be indistinguishable from omitting `schedule`, and the report would stay scheduled.
    Editing a report does not affect runs that already exist.
    """
    try:
        await _verify_report_in_agent(report_id, agent_id)

        provided = (
            request.model_fields_set
            if hasattr(request, "model_fields_set")
            else request.__fields_set__
        )

        fields = {"updated_by": auth.get("user_id")}
        # name can't be cleared — a report must have one, so an explicit null is ignored.
        if "name" in provided and request.name is not None:
            fields["name"] = request.name
        if "report_instructions" in provided:
            fields["report_instructions"] = request.report_instructions
        if "analysis_prompt" in provided:
            fields["analysis_prompt"] = request.analysis_prompt
        # Likewise query_groups: a report needs at least one group.
        if "query_groups" in provided and request.query_groups is not None:
            limit = await db_utils.get_effective_query_limit(agent_id)
            _validate_query_groups(request.query_groups, limit)
            fields["query_groups"] = _groups_to_dicts(request.query_groups)
        if "schedule" in provided:
            if request.schedule is not None:
                _validate_schedule(request.schedule)
                fields["schedule"] = _dump(request.schedule)
            else:
                fields["schedule"] = None  # the db layer clears next_run_at with it

        await db_utils.update_report(report_id, fields)
        return {"message": "Report updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating report {report_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/agents/{agent_id}/reports/{report_id}", response_model=MessageResponse)
async def delete_report(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("delete")),
):
    """
    Delete a report

    Soft delete: the row is kept with `deleted_at`/`deleted_by` so the change stays auditable,
    the report stops appearing and stops firing, and its historical runs remain reachable by id.
    """
    try:
        await _verify_report_in_agent(report_id, agent_id)
        await db_utils.soft_delete_report(report_id, deleted_by=auth.get("user_id"))
        return {"message": "Report deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting report {report_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@router.post(
    "/agents/{agent_id}/reports/{report_id}/runs",
    response_model=RunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_report(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Run a report now

    Accepted immediately and executed in the background — poll `.../runs/{run_id}/status` for
    progress. Every trigger creates a NEW run, and all runs are retained under the report so
    results can be compared over time.
    """
    try:
        await _verify_report_in_agent(report_id, agent_id)
        try:
            run = await db_utils.create_run(
                report_id, trigger="manual", user_id=auth.get("user_id")
            )
        except db_utils.QueryLimitExceeded as e:
            raise HTTPException(status_code=400, detail=_query_limit_message(e.limit))
        if not run:
            raise HTTPException(status_code=404, detail="Report not found")

        await start_run(run["run_id"])
        return {"run_id": run["run_id"], "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting run for report {report_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/reports/{report_id}/runs", response_model=RunListResponse)
async def list_runs(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """List the report's runs with their progress, newest first."""
    try:
        await _verify_report_in_agent(report_id, agent_id)
        return {"runs": await db_utils.list_runs(report_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing runs for report {report_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get(
    "/agents/{agent_id}/reports/{report_id}/runs/{run_id}/status",
    response_model=RunStatusResponse,
)
async def get_run_status(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    run_id: str = Path(..., description="Run ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    Poll a run's status and progress

    Progress is derived from the results stored so far, so it can only ever describe rows that
    actually exist.
    """
    try:
        return await _verify_run_in_report(run_id, report_id, agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status for run {run_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/reports/{report_id}/runs/{run_id}/export")
async def export_run(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    run_id: str = Path(..., description="Run ID"),
    format: str = Query(
        "json",
        description="json (full run data), md (human-readable report) or csv (one row per query)",
    ),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    Download a run

    Rendered on demand from the stored run — exports are never persisted, so there is no stale
    copy to serve. Available at any point in a run's life; an unfinished run simply exports the
    results it has.
    """
    fmt = (format or "json").lower()
    if fmt not in EXPORTERS:
        raise HTTPException(status_code=400, detail="format must be one of: json, md, csv")

    try:
        await _verify_run_in_report(run_id, report_id, agent_id)
        run = await db_utils.get_run_full(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        renderer, media_type, ext = EXPORTERS[fmt]
        return Response(
            content=renderer(run),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="report_run_{run_id}.{ext}"'
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting run {run_id} as {fmt}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/reports/{report_id}/runs/{run_id}")
async def get_run(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    run_id: str = Path(..., description="Run ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    Retrieve the full run

    Every question with its answer and execution details (the executed SQL, the tables and
    database used, the result table, chart data and export link — subject to the agent's own
    `show_sql_query`/`show_db_result` settings), plus the run summary and, when the report had
    an analysis prompt, the overall analysis. Sequential groups also carry a `conversation_flow`.
    """
    try:
        await _verify_run_in_report(run_id, report_id, agent_id)
        run = await db_utils.get_run_full(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting run {run_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    "/agents/{agent_id}/reports/{report_id}/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
)
async def cancel_run(
    agent_id: str = Path(..., description="Agent ID"),
    report_id: str = Path(..., description="Report ID"),
    run_id: str = Path(..., description="Run ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Cancel a run

    Soft cancel: the run is marked `cancelled` and no further queries are started. A query
    already in flight is not interrupted, and results that arrive for it are kept. Cancelling a
    run that already finished is a no-op — the response reports the state it actually has.
    """
    try:
        await _verify_run_in_report(run_id, report_id, agent_id)
        result = await db_utils.cancel_run(run_id, cancelled_by=auth.get("user_id"))
        return {"run_id": run_id, "status": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling run {run_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
