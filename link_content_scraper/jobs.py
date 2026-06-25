# ABOUTME: Async-safe store for completed scrape-job artifacts and ownership.
# ABOUTME: Owns result lookup, owner authorization, and delayed ZIP cleanup.
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import CLEANUP_DELAY_SECONDS

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """A completed scrape job's downloadable artifact and its owner."""

    zip_path: str
    customer_id: str


class JobStore:
    """Async-safe store mapping job/tracker ids to results and owners.

    Encapsulates the lifecycle of completed scrape artifacts: result lookup
    with ownership checks, tracker-ownership bookkeeping, and delayed cleanup
    of ZIP files. Replaces the bare module-global dicts that previously lived
    in the routes layer.
    """

    def __init__(self, cleanup_delay: float = CLEANUP_DELAY_SECONDS) -> None:
        self._results: dict[str, JobResult] = {}
        self._owners: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._cleanup_delay = cleanup_delay
        # Strong refs to background cleanup tasks so they aren't GC'd mid-run.
        self._background_tasks: set[asyncio.Task] = set()

    # -- Tracker ownership -----------------------------------------------------

    async def claim_tracker(self, tracker_id: str, customer_id: str) -> None:
        """Record which customer owns an in-progress tracker."""
        async with self._lock:
            self._owners[tracker_id] = customer_id

    async def tracker_owner(self, tracker_id: str) -> str | None:
        """Return the customer that owns a tracker, or None if untracked."""
        async with self._lock:
            return self._owners.get(tracker_id)

    async def release_tracker(self, tracker_id: str) -> None:
        """Forget a tracker's ownership (idempotent)."""
        async with self._lock:
            self._owners.pop(tracker_id, None)

    # -- Results ---------------------------------------------------------------

    async def store_result(self, job_id: str, zip_path: str, customer_id: str) -> None:
        """Record a completed job's downloadable ZIP and its owner."""
        async with self._lock:
            self._results[job_id] = JobResult(zip_path=zip_path, customer_id=customer_id)

    async def get_result(self, job_id: str, customer_id: str) -> JobResult | None:
        """Return a job's result only if owned by ``customer_id``.

        Returns None for both unknown jobs and ownership mismatches so callers
        cannot distinguish the two (avoids leaking job existence).
        """
        async with self._lock:
            entry = self._results.get(job_id)
        if entry is None or entry.customer_id != customer_id:
            return None
        return entry

    async def _discard_result(self, job_id: str) -> None:
        async with self._lock:
            self._results.pop(job_id, None)

    # -- Cleanup ---------------------------------------------------------------

    def schedule_cleanup(self, job_id: str, zip_path: str) -> asyncio.Task:
        """Schedule deletion of a job's ZIP after the configured delay."""
        task = asyncio.create_task(self._cleanup(job_id, zip_path))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _cleanup(self, job_id: str, zip_path: str) -> None:
        await asyncio.sleep(self._cleanup_delay)
        try:
            Path(zip_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to clean up %s", zip_path)
        finally:
            await self._discard_result(job_id)


# Singleton shared across the application.
job_store = JobStore()
