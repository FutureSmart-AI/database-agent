"""
Utility functions for retrieving and aggregating usage events.
"""

import math
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from models.sql_models import UsageEvent, UsageMetricRow as UsageMetric
from api.v1.schemas.usage_events import (
    UsageEventResponse,
    EventMetricResponse,
    UsageEventsListResponse,
    AggregatedUsageResponse,
    AggregatedMetric,
    UsageSummaryResponse,
    ServiceOperationSummary
)
from logger import logger
from otel_tracing import track_time


# Dimensions that live inside the `metadata` JSONB rather than in a column of their own.
# The Usage screen's model table and every one of its breakdown drawers split by model and
# provider, and neither is a column on usage_events.
#
# `model` is COALESCED because the writers disagree. Every graph node in `agent/nodes`
# records `metadata.model`, while `UsageTracker.record_llm_call` - the path the CSV agent
# uses - records `metadata.model_name`. Grouping on either key alone would silently drop
# the other writer's rows into a null bucket and under-report that model.
#
# A NULL group is meaningful, not missing: `db_query` and `code_execution` events have no
# model at all, so they aggregate under model=None. The screen renders that as "no
# model-level detail for this metric" rather than inventing a row.
_JSON_DIMENSIONS = {
    "model": func.coalesce(
        UsageEvent.event_metadata["model"].astext,
        UsageEvent.event_metadata["model_name"].astext,
    ),
    "provider": UsageEvent.event_metadata["provider"].astext,
}

# Whose credentials paid. The Usage screen offers three consumption sources and computes
# Total as platform + owner rather than over the merged row set, so a row with a NULL
# key_type would be excluded by BOTH halves and silently vanish from every figure on the
# screen. In production that is not a rounding error: the writers that omit key_type
# (the standalone chart API, and sql_exec's db_query events) accounted for 18.7% of all
# tokens over a 30-day window.
#
# An absent key_type reads as PLATFORM, which is the substantive truth rather than a
# convenience: if the customer's own credential did not pay for the work, FutureSmart's
# did. It is applied on read so the whole history is corrected at once, with no backfill
# and nothing to keep in step for rows written from now on.
#
# Consequence worth knowing: `key_type=platform-key` matches NULL rows too, and
# `group_by=key_type` never returns a null group.
PLATFORM_KEY = "platform-key"
OWNER_KEY = "owner-key"

# The Usage screen's "Functional Label" facet: the four phases a reader recognises,
# rather than the pipeline step names the events carry. One phase spans several labels, so
# it cannot be expressed by filtering `label` (which takes a single value) and has to be a
# dimension of its own.
#
# Mapping only — no event stores a phase, and none should: a phase is an opinion about how
# to present the pipeline, and baking it into written rows would mean re-writing history
# every time that opinion changed.
#
# A label absent from this map groups under NULL rather than being dropped, so a newly
# added node shows up as unclassified instead of silently vanishing from the totals.
PHASE_BY_LABEL = {
    "supervisor_routing": "Checking",
    "db_routing": "Checking",
    "fewshot_retrieval": "Preparing",
    "fewshot_indexing": "Preparing",
    "pandas_agent": "Preparing",
    "pandas_agent_routing": "Preparing",
    "pandas_execution": "Preparing",
    "sql_generation": "Extracting",
    "nl2sql_db_execution": "Extracting",
    "final_answer_generation": "Answering",
    "chart_generation": "Answering",
    "csv_api_request": "Answering",
}

PHASES = ["Checking", "Preparing", "Extracting", "Answering"]

_DERIVED_DIMENSIONS = {
    "key_type": func.coalesce(UsageEvent.key_type, PLATFORM_KEY),
    "phase": case(PHASE_BY_LABEL, value=UsageEvent.label, else_=None),
}

# Rolling block sizes for the trend series, in days. Rolling rather than calendar-aligned
# so the last bucket always ends now: a calendar-aligned final bucket is partial, and a
# partial bucket on a line chart reads as a collapse in usage that did not happen.
TREND_BUCKETS = {"day": 1, "week": 7, "month": 30}


def _dimension(field):
    """The SQL expression for a group-by/filter dimension.

    Three kinds: read out of the `metadata` JSONB, a column with a derivation applied, or
    a plain column. Returns None for anything this table cannot group by.
    """
    if field in _JSON_DIMENSIONS:
        return _JSON_DIMENSIONS[field]
    if field in _DERIVED_DIMENSIONS:
        return _DERIVED_DIMENSIONS[field]
    return getattr(UsageEvent, field, None)


@track_time("DB: Query Usage Events")
async def get_usage_events(
    session: AsyncSession,
    owner_id: Optional[str] = None,
    key_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    service_id: Optional[str] = None,
    operation: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0
) -> UsageEventsListResponse:
    """
    Retrieve paginated usage events with optional filters.

    Args:
        session: Database session
        owner_id: Filter by owner
        key_type: Filter by key type ('platform-key' or 'owner-key' for cost tracking)
        agent_id: Filter by agent
        service_id: Filter by service instance
        operation: Filter by operation
        start_date: Filter events after this date
        end_date: Filter events before this date
        limit: Maximum number of events to return
        offset: Number of events to skip

    Returns:
        UsageEventsListResponse with paginated events
    """
    logger.info(f"Retrieving usage events: owner_id={owner_id}, key_type={key_type}, "
                f"agent_id={agent_id}, service_id={service_id}, "
                f"operation={operation}, limit={limit}, offset={offset}")

    # Build filters
    filters = []
    if owner_id:
        filters.append(UsageEvent.owner_id == owner_id)
    if key_type:
        # Through the derived expression, exactly as the aggregate does. Filtering the raw
        # column here instead would make this list disagree with the totals it drills into:
        # a card counting a NULL-key_type row as platform, and the row list behind that
        # card omitting it, is the kind of mismatch a reader reports as missing data.
        filters.append(_DERIVED_DIMENSIONS["key_type"] == key_type)
    if agent_id:
        filters.append(UsageEvent.agent_id == agent_id)
    if service_id:
        filters.append(UsageEvent.service_id == service_id)
    if operation:
        filters.append(UsageEvent.operation == operation)
    if start_date:
        filters.append(UsageEvent.timestamp >= start_date)
    if end_date:
        filters.append(UsageEvent.timestamp <= end_date)
    
    # Count total matching events
    count_query = select(func.count()).select_from(UsageEvent)
    if filters:
        count_query = count_query.where(and_(*filters))
    
    result = await session.execute(count_query)
    total_count = result.scalar() or 0
    
    # Get paginated events
    query = select(UsageEvent).where(and_(*filters)) if filters else select(UsageEvent)
    query = query.order_by(UsageEvent.timestamp.desc()).limit(limit).offset(offset)
    
    result = await session.execute(query)
    events_db = result.scalars().all()
    
    # Fetch metrics for all events
    event_ids = [event.event_id for event in events_db]
    metrics_query = select(UsageMetric).where(UsageMetric.event_id.in_(event_ids))
    metrics_result = await session.execute(metrics_query)
    all_metrics = metrics_result.scalars().all()
    
    # Group metrics by event_id
    metrics_by_event = {}
    for metric in all_metrics:
        if metric.event_id not in metrics_by_event:
            metrics_by_event[metric.event_id] = []
        metrics_by_event[metric.event_id].append(
            EventMetricResponse(name=metric.metric_name, value=float(metric.metric_value))
        )
    
    # Build response
    events_response = []
    for event in events_db:
        events_response.append(UsageEventResponse(
            event_id=str(event.event_id),
            owner_id=event.owner_id,
            key_type=event.key_type,
            agent_id=event.agent_id,
            service_id=event.service_id,
            service_type=event.service_type,
            operation=event.operation,
            timestamp=event.timestamp.isoformat(),
            label=event.label,
            session_id=event.session_id,
            request_id=event.request_id,
            operation_id=event.operation_id,
            metadata=event.event_metadata,
            metrics=metrics_by_event.get(event.event_id, []),
            created_at=event.created_at.isoformat()
        ))
    
    logger.info(f"Retrieved {len(events_response)} events out of {total_count} total")

    return UsageEventsListResponse(
        total_count=total_count,
        events=events_response,
        limit=limit,
        offset=offset
    )


@track_time("DB: Aggregate Usage Metrics")
async def get_aggregated_usage(
    session: AsyncSession,
    owner_id: Optional[str] = None,
    key_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    service_id: Optional[str] = None,
    operation: Optional[str] = None,
    label: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    phase: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    group_by: List[str] = None
) -> AggregatedUsageResponse:
    """
    Get aggregated usage metrics grouped by specified dimensions.

    Args:
        session: Database session
        owner_id: Filter by owner
        key_type: Filter by key type ('platform-key' or 'owner-key' for cost tracking)
        agent_id: Filter by agent
        service_id: Filter by service instance
        operation: Filter by operation
        label: Filter by label
        model: Filter by model name (metadata.model, falling back to metadata.model_name)
        provider: Filter by provider (metadata.provider)
        phase: Filter by functional label (Checking/Preparing/Extracting/Answering)
        start_date: Filter events after this date
        end_date: Filter events before this date
        group_by: List of fields to group by (e.g., ['service_type', 'operation'])

    Returns:
        AggregatedUsageResponse with grouped metrics
    """
    logger.info(f"Aggregating usage: owner_id={owner_id}, key_type={key_type}, "
                f"agent_id={agent_id}, service_id={service_id}, "
                f"operation={operation}, group_by={group_by}")

    if not group_by:
        group_by = ['service_type', 'operation']

    # Build filters for events
    filters = []
    if owner_id:
        filters.append(UsageEvent.owner_id == owner_id)
    if key_type:
        # Through the derived expression, so filtering to platform includes the rows that
        # never recorded a key_type. See the note on _DERIVED_DIMENSIONS.
        filters.append(_DERIVED_DIMENSIONS["key_type"] == key_type)
    if agent_id:
        filters.append(UsageEvent.agent_id == agent_id)
    if service_id:
        filters.append(UsageEvent.service_id == service_id)
    if operation:
        filters.append(UsageEvent.operation == operation)
    if label:
        filters.append(UsageEvent.label == label)
    if model:
        filters.append(_JSON_DIMENSIONS["model"] == model)
    if provider:
        filters.append(_JSON_DIMENSIONS["provider"] == provider)
    if phase:
        filters.append(_DERIVED_DIMENSIONS["phase"] == phase)
    if start_date:
        filters.append(UsageEvent.timestamp >= start_date)
    if end_date:
        filters.append(UsageEvent.timestamp <= end_date)

    # Build group by columns. A JSONB-derived dimension is labelled so the SELECT and the
    # GROUP BY reference the same expression.
    group_columns = []
    resolved_fields = []
    for field in group_by:
        expr = _dimension(field)
        if expr is None:
            continue
        derived = field in _JSON_DIMENSIONS or field in _DERIVED_DIMENSIONS
        group_columns.append(expr.label(field) if derived else expr)
        resolved_fields.append(field)

    if not group_columns:
        raise ValueError("Invalid group_by fields")

    # Report back exactly what was grouped, so a caller that passed an unknown dimension
    # cannot read the result as though it had been applied.
    group_by = resolved_fields

    # Query: Group events and count
    query = select(
        *group_columns,
        func.count(UsageEvent.event_id).label('event_count')
    )

    if filters:
        query = query.where(and_(*filters))

    query = query.group_by(*group_columns)

    result = await session.execute(query)
    groups_data = result.all()

    # For each group, get aggregated metrics
    groups = []
    for row in groups_data:
        group_dict = {}
        for i, field in enumerate(group_by):
            group_dict[field] = row[i]
        group_dict['event_count'] = row[-1]

        # Get metrics for this group
        metric_filters = filters.copy()
        for i, field in enumerate(group_by):
            expr = _dimension(field)
            # `IS NULL`, not `= NULL`: model/provider are legitimately absent on database
            # and code-execution events, and that group's metrics must still be summed.
            metric_filters.append(expr.is_(None) if row[i] is None else expr == row[i])

        # Query aggregated metrics
        metrics_query = select(
            UsageMetric.metric_name,
            func.sum(UsageMetric.metric_value).label('total'),
            func.avg(UsageMetric.metric_value).label('avg'),
            func.min(UsageMetric.metric_value).label('min'),
            func.max(UsageMetric.metric_value).label('max'),
            func.count(UsageMetric.metric_id).label('count')
        ).join(
            UsageEvent, UsageMetric.event_id == UsageEvent.event_id
        ).where(
            and_(*metric_filters)
        ).group_by(
            UsageMetric.metric_name
        )

        metrics_result = await session.execute(metrics_query)
        metrics_data = metrics_result.all()

        group_dict['metrics'] = [
            AggregatedMetric(
                metric_name=m[0],
                total=float(m[1]),
                avg=float(m[2]),
                min=float(m[3]),
                max=float(m[4]),
                count=m[5]
            ).model_dump()
            for m in metrics_data
        ]

        groups.append(group_dict)

    logger.info(f"Aggregated into {len(groups)} groups")

    return AggregatedUsageResponse(
        group_by=group_by,
        groups=groups
    )


@track_time("DB: Get Owner Usage Summary")
async def get_usage_summary(
    session: AsyncSession,
    owner_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> UsageSummaryResponse:
    """
    Get usage summary for an owner grouped by service and operation.

    Args:
        session: Database session
        owner_id: Owner to get summary for
        start_date: Filter events after this date
        end_date: Filter events before this date

    Returns:
        UsageSummaryResponse with summary by service and operation
    """
    logger.info(f"Getting usage summary for owner_id={owner_id}")

    # Build filters
    filters = [UsageEvent.owner_id == owner_id]
    if start_date:
        filters.append(UsageEvent.timestamp >= start_date)
    if end_date:
        filters.append(UsageEvent.timestamp <= end_date)

    # Get total event count
    count_query = select(func.count()).select_from(UsageEvent).where(and_(*filters))
    result = await session.execute(count_query)
    total_events = result.scalar() or 0

    # Group by service_type and operation
    query = select(
        UsageEvent.service_type,
        UsageEvent.operation,
        func.count(UsageEvent.event_id).label('event_count')
    ).where(
        and_(*filters)
    ).group_by(
        UsageEvent.service_type,
        UsageEvent.operation
    )

    result = await session.execute(query)
    groups_data = result.all()

    # For each service/operation, get aggregated metrics
    services = []
    for row in groups_data:
        service_type = row[0]
        operation = row[1]
        event_count = row[2]

        # Get metrics for this service/operation
        metric_filters = filters + [
            UsageEvent.service_type == service_type,
            UsageEvent.operation == operation
        ]

        metrics_query = select(
            UsageMetric.metric_name,
            func.sum(UsageMetric.metric_value).label('total'),
            func.avg(UsageMetric.metric_value).label('avg'),
            func.min(UsageMetric.metric_value).label('min'),
            func.max(UsageMetric.metric_value).label('max'),
            func.count(UsageMetric.metric_id).label('count')
        ).join(
            UsageEvent, UsageMetric.event_id == UsageEvent.event_id
        ).where(
            and_(*metric_filters)
        ).group_by(
            UsageMetric.metric_name
        )

        metrics_result = await session.execute(metrics_query)
        metrics_data = metrics_result.all()

        metrics = [
            AggregatedMetric(
                metric_name=m[0],
                total=float(m[1]),
                avg=float(m[2]),
                min=float(m[3]),
                max=float(m[4]),
                count=m[5]
            )
            for m in metrics_data
        ]

        services.append(ServiceOperationSummary(
            service_type=service_type,
            operation=operation,
            event_count=event_count,
            metrics=metrics
        ))

    logger.info(f"Summary for {owner_id}: {total_events} events across {len(services)} service/operation combinations")

    return UsageSummaryResponse(
        owner_id=owner_id,
        start_date=start_date.isoformat() if start_date else "",
        end_date=end_date.isoformat() if end_date else "",
        total_events=total_events,
        services=services
    )


@track_time("DB: Usage Trend")
async def get_usage_trend(
    session: AsyncSession,
    owner_id: Optional[str] = None,
    key_type: Optional[str] = None,
    agent_id: Optional[str] = None,
    service_id: Optional[str] = None,
    operation: Optional[str] = None,
    label: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    phase: Optional[str] = None,
    days: int = 30,
    bucket: str = "day",
) -> Dict[str, Any]:
    """Usage over time, in rolling buckets ending now — the Usage screen's trend chart.

    Buckets are ROLLING blocks anchored at now, not calendar days/weeks/months. A
    calendar-aligned last bucket is partial, and a partial bucket at the right-hand edge of
    a line chart reads as a sudden collapse in usage rather than as "the week isn't over".

    ZERO-FILLED and dense: every bucket in the window is returned even when nothing
    happened in it. A line chart that silently skips empty buckets draws a straight line
    across a gap and implies usage that never occurred.

    Takes the same filters as `get_aggregated_usage`, so the chart can never disagree with
    the cards above it about which rows it is describing.

    Each bucket carries `event_count` plus the summed value of every metric recorded in it,
    so one call serves the tokens, requests and cost views of the chart.
    """
    size = TREND_BUCKETS.get(bucket)
    if not size:
        raise ValueError(
            f"invalid bucket {bucket!r}; allowed: {sorted(TREND_BUCKETS)}"
        )
    if days < 1:
        raise ValueError("days must be at least 1")

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    filters = [UsageEvent.timestamp >= window_start]
    if owner_id:
        filters.append(UsageEvent.owner_id == owner_id)
    if key_type:
        filters.append(_DERIVED_DIMENSIONS["key_type"] == key_type)
    if agent_id and service_id:
        filters.append(or_(UsageEvent.agent_id == agent_id,
                           UsageEvent.service_id == service_id))
    elif agent_id:
        filters.append(UsageEvent.agent_id == agent_id)
    elif service_id:
        filters.append(UsageEvent.service_id == service_id)
    if operation:
        filters.append(UsageEvent.operation == operation)
    if label:
        filters.append(UsageEvent.label == label)
    if model:
        filters.append(_JSON_DIMENSIONS["model"] == model)
    if provider:
        filters.append(_JSON_DIMENSIONS["provider"] == provider)
    if phase:
        filters.append(_DERIVED_DIMENSIONS["phase"] == phase)

    # Bucket 0 is the most recent block; index grows going back in time. Computed in SQL so
    # the grouping happens in the database rather than by pulling every event into Python.
    age_days = func.floor(
        func.extract("epoch", func.cast(now, UsageEvent.timestamp.type) - UsageEvent.timestamp)
        / 86400.0
    )
    idx = func.floor(age_days / float(size)).label("idx")

    counts = {r[0]: int(r[1] or 0) for r in (await session.execute(
        select(idx, func.count(UsageEvent.event_id))
        .where(and_(*filters))
        .group_by(idx)
    )).all()}

    metric_rows = (await session.execute(
        select(idx, UsageMetric.metric_name, func.sum(UsageMetric.metric_value))
        .select_from(UsageEvent)
        .join(UsageMetric, UsageMetric.event_id == UsageEvent.event_id)
        .where(and_(*filters))
        .group_by(idx, UsageMetric.metric_name)
    )).all()
    metrics_by_idx: Dict[int, Dict[str, float]] = {}
    for i, name, total in metric_rows:
        metrics_by_idx.setdefault(int(i), {})[name] = float(total or 0)

    n = max(1, math.ceil(days / size))
    series = []
    # Oldest bucket first, so the caller can plot the array left to right as given.
    for i in range(n - 1, -1, -1):
        end = now - timedelta(days=i * size)
        start = end - timedelta(days=size)
        series.append({
            "bucket_start": max(start, window_start).isoformat(),
            "bucket_end": end.isoformat(),
            "event_count": counts.get(i, 0),
            "metrics": metrics_by_idx.get(i, {}),
        })

    return {
        "bucket": bucket,
        "bucket_days": size,
        "days": days,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "series": series,
    }
