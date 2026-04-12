import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Thread/async-safe progress tracking for scrape jobs.

    All mutations go through an asyncio.Lock so concurrent tasks
    can safely update counters.
    """

    def __init__(self) -> None:
        self._trackers: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    def _ensure(self, tracker_id: str) -> dict:
        if tracker_id not in self._trackers:
            self._trackers[tracker_id] = {
                "total": 0,
                "processed": 0,
                "successful": 0,
                "potential_successful": 0,
                "skipped": 0,
                "failed": 0,
                "current_url": "",
                "cancelled": False,
                "tasks": [],
            }
        return self._trackers[tracker_id]

    async def init(self, tracker_id: str, total: int, processed: int = 0) -> None:
        async with self._lock:
            t = self._ensure(tracker_id)
            t["total"] = total
            t["processed"] = processed

    async def update(self, tracker_id: str, **kwargs: object) -> None:
        async with self._lock:
            t = self._ensure(tracker_id)
            for key, value in kwargs.items():
                if key in t:
                    t[key] = value

    async def increment(self, tracker_id: str, **kwargs: int) -> None:
        async with self._lock:
            t = self._ensure(tracker_id)
            for key, delta in kwargs.items():
                if key in t and isinstance(t[key], int):
                    t[key] += delta

    async def get(self, tracker_id: str) -> dict:
        async with self._lock:
            return dict(self._ensure(tracker_id))

    async def is_cancelled(self, tracker_id: str) -> bool:
        async with self._lock:
            return self._ensure(tracker_id).get("cancelled", False)

    async def cancel(self, tracker_id: str) -> bool:
        """Mark a tracker as cancelled and cancel its running tasks.

        Returns True if the tracker existed and was cancelled.
        """
        async with self._lock:
            if tracker_id not in self._trackers:
                return False
            t = self._trackers[tracker_id]
            t["cancelled"] = True
            for task in t.get("tasks", []):
                if not task.done():
                    task.cancel()
            return True

    async def register_tasks(self, tracker_id: str, tasks: list[asyncio.Task]) -> None:
        async with self._lock:
            self._ensure(tracker_id)["tasks"].extend(tasks)

    async def remove(self, tracker_id: str) -> dict:
        async with self._lock:
            return self._trackers.pop(tracker_id, {})

    async def exists(self, tracker_id: str) -> bool:
        async with self._lock:
            return tracker_id in self._trackers

    async def generate_events(self, tracker_id: str) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted progress events until processing is complete or cancelled."""
        while True:
            state = await self.get(tracker_id)
            if state["cancelled"]:
                data = {
                    "total": state["total"],
                    "processed": state["processed"],
                    "successful": state["potential_successful"],
                    "skipped": state["skipped"],
                    "failed": state["failed"],
                    "current_url": "",
                    "cancelled": True,
                }
                yield f"data: {json.dumps(data)}\n\n"
                return

            if state["processed"] >= state["total"] and state["total"] > 0:
                break

            data = {
                "total": state["total"],
                "processed": state["processed"],
                "successful": state["potential_successful"],
                "skipped": state["skipped"],
                "failed": state["failed"],
                "current_url": state["current_url"],
            }
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.5)

        # Final update with confirmed successes
        state = await self.get(tracker_id)
        data = {
            "total": state["total"],
            "processed": state["processed"],
            "successful": state["successful"],
            "skipped": state["skipped"],
            "failed": state["failed"],
            "current_url": state["current_url"],
        }
        yield f"data: {json.dumps(data)}\n\n"


# Singleton instance shared across the application
progress_tracker = ProgressTracker()
