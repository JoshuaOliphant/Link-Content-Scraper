# ABOUTME: Unit tests for the async-safe ProgressTracker class.
# ABOUTME: Tests lock-protected counters, cancellation, SSE events, and lifecycle.

import asyncio
import json

import pytest

from link_content_scraper.progress import ProgressTracker


@pytest.fixture()
def tracker():
    return ProgressTracker()


class TestInit:
    async def test_init_sets_total_and_processed(self, tracker):
        await tracker.init("job1", total=10, processed=2)
        state = await tracker.get("job1")
        assert state["total"] == 10
        assert state["processed"] == 2

    async def test_init_defaults_processed_to_zero(self, tracker):
        await tracker.init("job1", total=5)
        state = await tracker.get("job1")
        assert state["processed"] == 0

    async def test_init_preserves_existing_updates(self, tracker):
        await tracker.init("job1", total=5)
        await tracker.update("job1", current_url="http://example.com")
        await tracker.init("job1", total=10)
        state = await tracker.get("job1")
        assert state["total"] == 10
        assert state["current_url"] == "http://example.com"


class TestIncrement:
    async def test_increment_adds_deltas(self, tracker):
        await tracker.init("job1", total=10)
        await tracker.increment("job1", processed=1, successful=1)
        state = await tracker.get("job1")
        assert state["processed"] == 1
        assert state["successful"] == 1

    async def test_increment_ignores_non_integer_fields(self, tracker):
        await tracker.init("job1", total=10)
        await tracker.update("job1", current_url="http://a.com")
        await tracker.increment("job1", current_url=1)
        state = await tracker.get("job1")
        assert state["current_url"] == "http://a.com"

    async def test_increment_creates_tracker_if_missing(self, tracker):
        await tracker.increment("new", processed=3)
        state = await tracker.get("new")
        assert state["processed"] == 3


class TestUpdate:
    async def test_update_sets_fields(self, tracker):
        await tracker.init("job1", total=5)
        await tracker.update("job1", current_url="http://x.com")
        state = await tracker.get("job1")
        assert state["current_url"] == "http://x.com"

    async def test_update_ignores_unknown_keys(self, tracker):
        await tracker.init("job1", total=5)
        await tracker.update("job1", bogus="x")
        state = await tracker.get("job1")
        assert "bogus" not in state


class TestCancel:
    async def test_cancel_marks_cancelled(self, tracker):
        await tracker.init("job1", total=5)
        result = await tracker.cancel("job1")
        assert result is True
        assert await tracker.is_cancelled("job1") is True

    async def test_cancel_cancels_registered_tasks(self, tracker):
        await tracker.init("job1", total=5)
        task = asyncio.create_task(asyncio.sleep(100))
        await tracker.register_tasks("job1", [task])
        await tracker.cancel("job1")
        # Yield control so the cancellation can take effect
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    async def test_register_tasks_creates_tracker_if_missing(self, tracker):
        """register_tasks for a fresh tracker_id must initialize a default state."""
        task = asyncio.create_task(asyncio.sleep(0))
        await tracker.register_tasks("brand_new", [task])
        await task
        state = await tracker.get("brand_new")
        assert state is not None
        assert state["total"] == 0
        assert task in state["tasks"]

    async def test_cancel_returns_false_for_unknown_id(self, tracker):
        result = await tracker.cancel("nope")
        assert result is False

    async def test_is_cancelled_false_by_default(self, tracker):
        await tracker.init("job1", total=5)
        assert await tracker.is_cancelled("job1") is False

    async def test_is_cancelled_false_for_unknown_id(self, tracker):
        assert await tracker.is_cancelled("nope") is False


class TestGet:
    async def test_get_returns_snapshot(self, tracker):
        await tracker.init("job1", total=5)
        snapshot = await tracker.get("job1")
        snapshot["total"] = 999
        state = await tracker.get("job1")
        assert state["total"] == 5

    async def test_get_returns_none_for_unknown_id(self, tracker):
        result = await tracker.get("nope")
        assert result is None


class TestLifecycle:
    async def test_exists_and_remove(self, tracker):
        await tracker.init("job1", total=5)
        assert await tracker.exists("job1") is True
        removed = await tracker.remove("job1")
        assert removed["total"] == 5
        assert await tracker.exists("job1") is False

    async def test_remove_returns_empty_for_unknown_id(self, tracker):
        removed = await tracker.remove("nope")
        assert removed == {}


class TestGenerateEvents:
    async def test_yields_sse_json(self, tracker):
        await tracker.init("job1", total=2, processed=0)
        await tracker.increment("job1", processed=1, potential_successful=1)

        # Collect one event then complete the job
        events = []
        async for event in tracker.generate_events("job1"):
            events.append(event)
            # After first event, mark job complete so generator terminates
            await tracker.update("job1", processed=2)
            await tracker.increment("job1", processed=1, potential_successful=1)

        assert len(events) >= 1
        # Parse the SSE data line
        data_str = events[0].replace("data: ", "").strip()
        data = json.loads(data_str)
        assert "total" in data
        assert "processed" in data
        assert "successful" in data

    async def test_terminates_on_completion(self, tracker):
        await tracker.init("job1", total=1, processed=1)
        await tracker.increment("job1", successful=1)

        events = []
        async for event in tracker.generate_events("job1"):
            events.append(event)

        # Should get exactly one final event
        assert len(events) == 1
        data = json.loads(events[0].replace("data: ", "").strip())
        assert data["processed"] >= data["total"]

    async def test_terminates_on_cancel(self, tracker):
        await tracker.init("job1", total=10, processed=0)

        events = []
        async for event in tracker.generate_events("job1"):
            events.append(event)
            await tracker.cancel("job1")

        last_data = json.loads(events[-1].replace("data: ", "").strip())
        assert last_data["cancelled"] is True

    async def test_timeout_on_missing_tracker(self, tracker, monkeypatch):
        # Reduce max wait iterations so test doesn't take 30 seconds
        import link_content_scraper.progress as progress_mod
        monkeypatch.setattr(progress_mod, "_MAX_WAIT_ITERATIONS", 2)

        events = []
        async for event in tracker.generate_events("never_created"):
            events.append(event)

        assert len(events) == 1
        data = json.loads(events[0].replace("data: ", "").strip())
        assert "error" in data
        assert "not found" in data["error"].lower()
