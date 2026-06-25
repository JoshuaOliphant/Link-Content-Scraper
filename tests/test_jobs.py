# ABOUTME: Unit tests for the JobStore — results, ownership, and cleanup contracts.
# ABOUTME: Exercises the store directly rather than through the HTTP routes.
import asyncio


from link_content_scraper.jobs import JobResult, JobStore


async def test_store_and_get_result_returns_entry_for_owner():
    store = JobStore()
    await store.store_result("job1", "/tmp/job1.zip", "cus_a")

    entry = await store.get_result("job1", "cus_a")
    assert entry == JobResult(zip_path="/tmp/job1.zip", customer_id="cus_a")


async def test_get_result_hides_jobs_owned_by_others():
    store = JobStore()
    await store.store_result("job1", "/tmp/job1.zip", "cus_a")

    # A different customer must not be able to see the job exists.
    assert await store.get_result("job1", "cus_b") is None


async def test_get_result_unknown_job_is_none():
    store = JobStore()
    assert await store.get_result("nope", "cus_a") is None


async def test_tracker_ownership_lifecycle():
    store = JobStore()
    assert await store.tracker_owner("t1") is None

    await store.claim_tracker("t1", "cus_a")
    assert await store.tracker_owner("t1") == "cus_a"

    await store.release_tracker("t1")
    assert await store.tracker_owner("t1") is None
    # Releasing again is a no-op, not an error.
    await store.release_tracker("t1")


async def test_schedule_cleanup_deletes_file_and_forgets_job(tmp_path):
    store = JobStore(cleanup_delay=0)
    zip_file = tmp_path / "done.zip"
    zip_file.write_bytes(b"PK\x03\x04")
    await store.store_result("job1", str(zip_file), "cus_a")

    task = store.schedule_cleanup("job1", str(zip_file))
    await task

    assert not zip_file.exists()
    assert await store.get_result("job1", "cus_a") is None


async def test_schedule_cleanup_tolerates_missing_file(tmp_path):
    store = JobStore(cleanup_delay=0)
    missing = tmp_path / "never-existed.zip"
    await store.store_result("job1", str(missing), "cus_a")

    # Must not raise even though the file is already gone.
    await store.schedule_cleanup("job1", str(missing))
    # Give the (already-awaited) task a tick to settle and confirm cleanup ran.
    await asyncio.sleep(0)
    assert await store.get_result("job1", "cus_a") is None
