"""
Database utilities functions for event recording with bulk insert optimization.

This module provides functions to record usage events with:
- Bulk insert optimization using asyncpg executemany
- Partial success handling (continue on individual failures)
- Transaction per event to avoid all-or-nothing
- Auto-generation of UUIDs for event_id and operation_id
- Timestamp validation before insert
- Detailed error collection for failed events
"""

from typing import List, Optional, Tuple
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from logger import logger
from api.v1.schemas.usage_events import (
    UsageEventRequest,
    UsageEventsResponse,
    FailedEvent,
)
from chatbot_management.services.sqlmodel_session import get_connection_pool
import json
from otel_tracing import track_time


@track_time("Node: Record Usage Events Batch")
async def record_usage_events(
    events: List[UsageEventRequest]
) -> UsageEventsResponse:
    """
    Record usage events with partial success handling.
    Returns processed count, failed count, and error details.
    
    Args:
        events: List of usage events to record
        
    Returns:
        UsageEventsResponse with processed_count, failed_count, and failed_events
    """
    logger.info(f"Recording {len(events)} usage events")
    
    # Validate all events first
    failed_events: List[FailedEvent] = []
    valid_events: List[UsageEventRequest] = []
    
    for index, event in enumerate(events):
        failed = await validate_single_event(event, index)
        if failed:
            failed_events.append(failed)
        else:
            valid_events.append(event)
    
    # Auto-generate IDs for valid events
    valid_events_with_ids = [auto_generate_ids(event) for event in valid_events]
    
    # Batch insert valid events
    if valid_events_with_ids:
        success_count, insert_failures = await insert_events_batch(valid_events_with_ids)
        failed_events.extend(insert_failures)
    else:
        success_count = 0
    
    response = UsageEventsResponse(
        processed_count=success_count,
        failed_count=len(failed_events),
        failed_events=failed_events
    )
    
    logger.info(f"Recorded {success_count} events, {len(failed_events)} failed")
    return response


async def validate_single_event(
    event: UsageEventRequest,
    index: int
) -> Optional[FailedEvent]:
    """
    Validate a single event. Returns FailedEvent if invalid, None if valid.
    
    Args:
        event: Event to validate
        index: Index of event in request array
        
    Returns:
        FailedEvent if validation fails, None if valid
    """
    try:
        # Validate timestamp format and range
        try:
            dt = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            
            # Not in future
            if dt > now:
                return FailedEvent(
                    index=index,
                    error="timestamp cannot be in the future",
                    event=event.model_dump()
                )
            
            # Not older than 7 days
            if (now - dt) > timedelta(days=7):
                return FailedEvent(
                    index=index,
                    error="timestamp cannot be older than 7 days",
                    event=event.model_dump()
                )
        except (ValueError, AttributeError) as e:
            return FailedEvent(
                index=index,
                error=f"Invalid ISO8601 timestamp: {e}",
                event=event.model_dump()
            )
        
        # All validations passed
        return None
        
    except Exception as e:
        logger.error(f"Validation error for event {index}: {e}")
        return FailedEvent(
            index=index,
            error=f"Validation error: {str(e)}",
            event=event.model_dump() if hasattr(event, 'model_dump') else {}
        )


def auto_generate_ids(event: UsageEventRequest) -> UsageEventRequest:
    """
    Auto-generate event_id and operation_id if not provided.

    Args:
        event: Event to process

    Returns:
        Event with auto-generated IDs
    """
    # Create a copy of the event data
    event_data = event.model_dump()

    # Auto-generate operation_id if not provided
    if not event_data.get('operation_id'):
        event_data['operation_id'] = str(uuid4())

    # Note: event_id is generated at database level or in insert function
    # We don't set it here as it's not part of the request model

    return UsageEventRequest(**event_data)


@track_time("DB: Insert Usage Events Batch")
async def insert_events_batch(
    events: List[UsageEventRequest]
) -> Tuple[int, List[FailedEvent]]:
    """
    Batch insert events and metrics. Returns (success_count, failed_events).
    Uses asyncpg executemany for performance.

    Each event is inserted in its own transaction to ensure partial success.
    If an event fails, we continue with the next one.

    Args:
        events: List of validated events with auto-generated IDs

    Returns:
        Tuple of (success_count, failed_events)
    """
    success_count = 0
    failed_events: List[FailedEvent] = []

    # Take a connection from this repo's shared asyncpg pool. The usage service opened a
    # fresh connection per batch; here events are written on every LLM call, so per-batch
    # connect/teardown would be constant churn against the database the chat flow is using.
    try:
        pool = await get_connection_pool()
        conn = await pool.acquire()
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        # All events fail if we can't connect
        for index, event in enumerate(events):
            failed_events.append(FailedEvent(
                index=index,
                error=f"Database connection failed: {str(e)}",
                event=event.model_dump()
            ))
        return 0, failed_events

    try:
        # Process each event in its own transaction for partial success
        for index, event in enumerate(events):
            try:
                # Start transaction for this event
                async with conn.transaction():
                    # Generate event_id
                    event_id = uuid4()

                    # Parse timestamp
                    timestamp = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))

                    # Prepare metadata as JSON string for JSONB column
                    metadata_json = json.dumps(event.metadata) if event.metadata else None

                    # Insert usage_event
                    # Note: service_type is now an Enum, so we need to get its value
                    await conn.execute(
                        """
                        INSERT INTO usage_events (
                            event_id, owner_id, key_type, agent_id, service_id,
                            service_type, operation, timestamp, label, session_id, request_id,
                            operation_id, metadata
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
                        """,
                        event_id,
                        event.owner_id,
                        event.key_type,      # 'platform-key' or 'owner-key' for cost tracking
                        event.agent_id,      # Can be None now
                        event.service_id,    # New field
                        event.service_type.value,  # Get enum value
                        event.operation,
                        timestamp,
                        event.label,
                        event.session_id,
                        event.request_id,
                        event.operation_id,
                        metadata_json
                    )

                    # Insert metrics if present using executemany for bulk optimization
                    if event.metrics:
                        # Prepare metrics data for executemany
                        # NOTE: metric_id is BIGSERIAL (auto-increment), so we don't insert it
                        metrics_data = [
                            (
                                event_id,           # event_id (FK)
                                metric.name,        # metric_name
                                float(metric.value) # metric_value (NUMERIC)
                            )
                            for metric in event.metrics
                        ]

                        # Batch insert metrics using executemany
                        # Column names: event_id, metric_name, metric_value
                        await conn.executemany(
                            """
                            INSERT INTO usage_metrics (event_id, metric_name, metric_value)
                            VALUES ($1, $2, $3)
                            """,
                            metrics_data
                        )

                    # Transaction commits automatically if no exception
                    success_count += 1
                    logger.debug(f"Successfully inserted event {index} with event_id {event_id}")

            except Exception as e:
                # Transaction rolls back automatically on exception
                logger.error(f"Failed to insert event {index}: {e}")
                failed_events.append(FailedEvent(
                    index=index,
                    error=f"Database insert failed: {str(e)}",
                    event=event.model_dump()
                ))
                # Continue with next event (partial success)
                continue

    finally:
        # Release, not close — closing a pooled connection shrinks the pool.
        await pool.release(conn)

    return success_count, failed_events

