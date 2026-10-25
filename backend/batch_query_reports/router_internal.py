"""Internal (worker-facing) Batch Query Reports API.

Prefix `/internal/runs` — full paths are `/nl2sql/api/internal/runs/...`. Service-to-service
only, master key required, never browser-facing.

This is how report runs are executed by default (`REPORTS_EXECUTOR=celery`): the
`fs-agent-workers` fleet picks up `workers.tasks.process_nl2sql_report_run`, fetches the
definition here, and posts status, results and the analysis summary back. The worker still asks
THIS service's `/v1/agents/{id}/chat` for each answer — it orchestrates, it does not replace the
agent.

The `inprocess` executor bypasses these endpoints entirely (it reaches the same `db_utils`
functions directly), so they are the seam for any out-of-process executor, not a second
implementation of the logic.

Idempotency is the hard requirement, because worker retries are normal:
- status transitions are no-ops when re-sent or once the run is terminal;
- results are upserted per (run_id, query_id).
"""
from fastapi import APIRouter, Depends, HTTPException, Path

from logger import logger

from batch_query_reports import db_utils
from batch_query_reports.dependencies import require_internal_service
from batch_query_reports.pydantic_models_restful import (
    AnalysisSubmitRequest,
    ResultsSubmitRequest,
    StatusUpdateRequest,
)

router = APIRouter(prefix="/internal/runs")


@router.get("/{run_id}", include_in_schema=False)
async def get_run_definition(
    run_id: str = Path(..., description="Run ID"),
    _auth: dict = Depends(require_internal_service),
):
    """Fetch the pre-materialized run definition, with the stable group and query IDs."""
    definition = await db_utils.get_run_definition(run_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Run not found")
    return definition


@router.get("/{run_id}/status", include_in_schema=False)
async def get_run_status(
    run_id: str = Path(..., description="Run ID"),
    _auth: dict = Depends(require_internal_service),
):
    """Current status + derived progress of a run.

    An executor polls this between queries so a cancel takes effect promptly. Without it a
    cancelled run would keep costing full agent pipelines whose results are then discarded by the
    terminal-state guard below — the user would be billed for work they explicitly stopped.

    Deliberately not the public status endpoint: that one enforces agent RBAC, which a worker has
    no user identity for.
    """
    status_obj = await db_utils.get_run_status(run_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Run not found")
    return status_obj


@router.post("/{run_id}/status", include_in_schema=False)
async def update_run_status(
    request: StatusUpdateRequest,
    run_id: str = Path(..., description="Run ID"),
    _auth: dict = Depends(require_internal_service),
):
    """Report a lifecycle transition (running / completed / failed). Idempotent."""
    try:
        result = await db_utils.update_run_status(
            run_id,
            status=request.status,
            started_at=request.started_at,
            ended_at=request.ended_at,
            failure_reason=request.failure_reason,
        )
    except Exception as e:
        logger.error(
            f"POST /internal/runs/{run_id}/status (status={request.status}) failed: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update run status")
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "status": result}


@router.post("/{run_id}/results", include_in_schema=False)
async def submit_results(
    request: ResultsSubmitRequest,
    run_id: str = Path(..., description="Run ID"),
    _auth: dict = Depends(require_internal_service),
):
    """Submit results as queries complete. Batchable, and idempotent per query_id.

    Mirrors the status guard: once a run is terminal, late results are dropped (200 with
    `results_written: 0`) rather than mutating a closed-out run — otherwise a retrying worker
    could add answers to a run the user already saw as failed or cancelled.
    """
    status_obj = await db_utils.get_run_status(run_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Run not found")

    if status_obj["status"] in db_utils.TERMINAL_RUN_STATES:
        logger.info(
            f"Dropping {len(request.results)} late result(s) for run {run_id} "
            f"(status={status_obj['status']})"
        )
        return {
            "run_id": run_id,
            "results_written": 0,
            "ignored": True,
            "reason": f"run is {status_obj['status']}",
        }

    items = [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in request.results]
    count = await db_utils.upsert_results(run_id, items)
    return {"run_id": run_id, "results_written": count}


@router.post("/{run_id}/analysis", include_in_schema=False)
async def submit_analysis(
    request: AnalysisSubmitRequest,
    run_id: str = Path(..., description="Run ID"),
    _auth: dict = Depends(require_internal_service),
):
    """Store the analysis-prompt output. Sent once, after every query has finished."""
    ok = await db_utils.set_run_analysis(run_id, request.overall_summary)
    if not ok:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "message": "Analysis stored"}
