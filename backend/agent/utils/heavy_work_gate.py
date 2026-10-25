"""One heavy database-setup section at a time per API process (DA-MEM-002).

Adding or changing a database starts background work that holds whole result sets in memory:
the HC column profiler, SELECT DISTINCT over every high-cardinality column, dense + BM25
embedding of those values and the Qdrant upsert, and the description job's schema inspection.
Each setup ran as its own unbounded task, so two databases added seconds apart ran both at
once; with a chat question on top the 1024 MB task was killed (OutOfMemoryError, exit 137).

Every such section runs inside `heavy_work(label)`. Callers wait in arrival order (asyncio
primitives are FIFO) and none is dropped. Chat requests never enter the gate. Work started
from inside a held section (directly, or in a task it awaits through gather or wait_for) passes
straight through while that section still holds the gate, so nesting cannot deadlock; anything
arriving after the section released queues like any other caller. The API runs one uvicorn worker per container, so this process-wide
gate bounds the whole container.
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

# Sections allowed to run at once. 1 is the measured-safe value for a 1024 MB task.
HEAVY_SETUP_CONCURRENCY = max(1, int(os.getenv("HEAVY_SETUP_CONCURRENCY", "1")))

class _Lease:
    """Held from acquire to release. Tasks copy the context, so a task spawned inside a section
    carries the lease and can tell whether that section still holds the gate."""
    active = True


_lease: ContextVar[Optional[_Lease]] = ContextVar("heavy_work_lease", default=None)
_semaphore: Optional[asyncio.Semaphore] = None
_semaphore_loop: Optional[asyncio.AbstractEventLoop] = None
_running = 0
_waiting = 0


def _gate() -> asyncio.Semaphore:
    """The semaphore for the running loop (a new loop, e.g. in tests, gets a fresh one)."""
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(HEAVY_SETUP_CONCURRENCY)
        _semaphore_loop = loop
    return _semaphore


def _memory() -> str:
    """Resident and peak memory of this process (Linux), so each section's cost is in the log."""
    try:
        with open("/proc/self/status") as f:
            fields = dict(line.split(":", 1) for line in f if line.startswith(("VmRSS", "VmHWM")))
        return " ".join(f"{k.strip()}={v.strip()}" for k, v in sorted(fields.items()))
    except OSError:
        return "memory=n/a"


def heavy_work_state() -> dict:
    """Current occupancy, for logs and tests."""
    return {"running": _running, "waiting": _waiting, "limit": HEAVY_SETUP_CONCURRENCY}


@asynccontextmanager
async def heavy_work(label: str) -> AsyncGenerator[None, None]:
    """Run the enclosed section only when no other heavy setup section is running."""
    global _running, _waiting
    held = _lease.get()
    if held is not None and held.active:
        yield
        return
    gate = _gate()
    queued_at = time.monotonic()
    _waiting += 1
    if gate.locked():
        logger.info(f"[heavy-work] queued {label} (running={_running}, waiting={_waiting})")
    try:
        await gate.acquire()
    finally:
        _waiting -= 1
    _running += 1
    lease = _Lease()
    token = _lease.set(lease)
    logger.info(f"[heavy-work] start {label} after {time.monotonic() - queued_at:.1f}s queued "
                f"(waiting={_waiting}) {_memory()}")
    try:
        yield
    finally:
        lease.active = False
        _lease.reset(token)
        _running -= 1
        gate.release()
        logger.info(f"[heavy-work] done {label} {_memory()}")
