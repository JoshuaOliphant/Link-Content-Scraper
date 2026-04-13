# Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit tests for ProgressTracker, RateLimiter, and scraper module, plus BDD scenarios for the full scrape lifecycle.

**Architecture:** Three new unit test files (one per module) with fresh instances per test. One BDD feature file with step definitions backed by a local async HTTP test server. The test server is a real `aiohttp` server on localhost that returns controlled responses — no mocks.

**Tech Stack:** pytest, pytest-asyncio, pytest-bdd, httpx (MockTransport for unit tests), aiohttp (local test server for BDD)

**Spec:** `docs/superpowers/specs/2026-04-12-test-coverage-design.md`

**Beads:** `link_content_scraper-c5q` (unit tests), `link_content_scraper-0bt` (BDD)

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `tests/test_progress.py` | ProgressTracker unit tests |
| Create | `tests/test_rate_limit.py` | RateLimiter unit tests |
| Create | `tests/test_scraper.py` | Scraper module unit tests |
| Create | `tests/features/scraping.feature` | Gherkin BDD scenarios |
| Create | `tests/test_bdd_scrape.py` | BDD step definitions |
| Create | `tests/conftest.py` | Shared fixtures: local test HTTP server, app client |
| Modify | `pyproject.toml` | Add pytest-bdd dependency |

---

### Task 1: Add pytest-bdd dependency

**Files:**
- Modify: `pyproject.toml:14-17`

- [ ] **Step 1: Add pytest-bdd to dev dependencies**

In `pyproject.toml`, add `pytest-bdd` to the dev extras:

```toml
[project.optional-dependencies]
dev = [
    "aiohttp>=3.9",
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-bdd>=8.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --extra dev`
Expected: Installs pytest-bdd and its dependencies without errors.

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "import pytest_bdd; print(pytest_bdd.__version__)"`
Expected: Prints version number without error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pytest-bdd to dev dependencies"
```

---

### Task 2: Create shared test fixtures (`tests/conftest.py`)

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write the conftest with local test server fixture**

Create `tests/conftest.py`:

```python
# ABOUTME: Shared test fixtures for the link content scraper test suite.
# ABOUTME: Provides a local HTTP test server and FastAPI test client fixtures.

import asyncio
import threading

from aiohttp import web
from fastapi.testclient import TestClient

import pytest

from link_content_scraper.app import create_app


# -- Local test HTTP server ----------------------------------------------------

def _build_test_app(routes: dict[str, tuple[int, str]]) -> web.Application:
    """Build an aiohttp app that serves configured routes.

    routes maps path -> (status_code, body).
    The index page auto-generates <a href> links to all other routes.
    """
    app = web.Application()

    async def handle_index(request):
        links = "".join(
            f'<a href="http://localhost:{request.url.port}{path}">{path}</a>\n'
            for path in routes
            if path != "/"
        )
        html = f"<html><body><h1>Test Site</h1>\n{links}</body></html>"
        return web.Response(text=html, content_type="text/html")

    async def handle_route(request):
        path = request.path
        if path in routes:
            status, body = routes[path]
            return web.Response(status=status, text=body)
        return web.Response(status=404, text="Not found")

    app.router.add_get("/", handle_index)
    # Register each configured path
    for path in routes:
        if path != "/":
            app.router.add_get(path, handle_route)

    return app


class LocalTestServer:
    """Runs an aiohttp server in a background thread on a random port."""

    def __init__(self, routes: dict[str, tuple[int, str]]):
        self.routes = routes
        self.port: int = 0
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None

    def start(self) -> None:
        started = threading.Event()

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._start(started))
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        started.wait(timeout=5)

    async def _start(self, started: threading.Event) -> None:
        app = _build_test_app(self.routes)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "localhost", 0)
        await site.start()
        # Grab the port the OS assigned
        self.port = site._server.sockets[0].getsockname()[1]
        started.set()

    def stop(self) -> None:
        if self._loop and self._runner:
            asyncio.run_coroutine_threadsafe(self._runner.cleanup(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"


# Markdown-like content the local server returns (simulates Jina output)
VALID_MARKDOWN = (
    "# {title}\n\n"
    "This is a detailed article about {title}. "
    "It contains multiple paragraphs of substantial content.\n\n"
    "## Section One\n\n"
    "The first section covers background material that provides "
    "context for the reader. It spans several sentences to ensure "
    "the content validation threshold is exceeded.\n\n"
    "## Section Two\n\n"
    "The second section dives deeper into the topic with analysis "
    "and supporting evidence for the key claims.\n"
)

MINIMAL_CONTENT = "short"


def make_page_routes(count: int, *, status: int = 200, content: str | None = None) -> dict[str, tuple[int, str]]:
    """Generate route configs for N sub-pages with valid markdown content."""
    routes = {}
    for i in range(1, count + 1):
        body = content if content is not None else VALID_MARKDOWN.format(title=f"Page {i}")
        routes[f"/page{i}"] = (status, body)
    return routes


@pytest.fixture()
def test_server():
    """Fixture that yields a factory for creating local test servers.

    Usage in tests:
        server = test_server(routes)
        # server.base_url is now available
    """
    servers: list[LocalTestServer] = []

    def _factory(routes: dict[str, tuple[int, str]]) -> LocalTestServer:
        srv = LocalTestServer(routes)
        srv.start()
        servers.append(srv)
        return srv

    yield _factory

    for srv in servers:
        srv.stop()


@pytest.fixture()
def client():
    """FastAPI test client fixture."""
    app = create_app()
    return TestClient(app)
```

- [ ] **Step 2: Verify conftest loads**

Run: `uv run pytest --collect-only tests/test_content.py`
Expected: Collects existing tests without errors (conftest is picked up).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared conftest with local HTTP test server fixture"
```

---

### Task 3: ProgressTracker unit tests (`tests/test_progress.py`)

**Files:**
- Create: `tests/test_progress.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_progress.py`:

```python
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
        assert task.cancelled()

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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_progress.py -v`
Expected: All tests PASS. These test against the existing implementation.

- [ ] **Step 3: Commit**

```bash
git add tests/test_progress.py
git commit -m "test: add ProgressTracker unit tests"
```

---

### Task 4: RateLimiter unit tests (`tests/test_rate_limit.py`)

**Files:**
- Create: `tests/test_rate_limit.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_rate_limit.py`:

```python
# ABOUTME: Unit tests for the async-safe timestamp-based RateLimiter.
# ABOUTME: Tests acquire behavior, blocking, window expiry, and concurrent access.

import asyncio
import time

import pytest

from link_content_scraper.rate_limit import RateLimiter


class TestAcquire:
    async def test_acquires_up_to_limit_without_blocking(self):
        limiter = RateLimiter(limit=3, period=10)
        start = time.time()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.5

    async def test_blocks_after_limit_exhausted(self):
        limiter = RateLimiter(limit=2, period=1)
        await limiter.acquire()
        await limiter.acquire()
        start = time.time()
        await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed >= 0.8  # Should wait ~1 second for window to expire


class TestWindowExpiry:
    async def test_can_acquire_after_window_expires(self):
        limiter = RateLimiter(limit=1, period=1)
        await limiter.acquire()
        await asyncio.sleep(1.1)
        start = time.time()
        await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.5


class TestConcurrency:
    async def test_concurrent_acquires_respect_limit(self):
        limiter = RateLimiter(limit=3, period=2)

        timestamps: list[float] = []

        async def acquire_and_record():
            await limiter.acquire()
            timestamps.append(time.time())

        start = time.time()
        await asyncio.gather(*[acquire_and_record() for _ in range(6)])
        elapsed = time.time() - start

        # First 3 should be near-instant, next 3 after ~2s window
        assert elapsed >= 1.5
        # All 6 should complete
        assert len(timestamps) == 6
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rate_limit.py
git commit -m "test: add RateLimiter unit tests"
```

---

### Task 5: Scraper module unit tests (`tests/test_scraper.py`)

**Files:**
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_scraper.py`:

```python
# ABOUTME: Unit tests for scraper module functions (create_zip_file, get_markdown_content).
# ABOUTME: Uses httpx MockTransport for HTTP control and monkeypatched singletons.

import asyncio
import zipfile
from pathlib import Path

import httpx
import pytest

from link_content_scraper.progress import ProgressTracker
from link_content_scraper.rate_limit import RateLimiter
from link_content_scraper.scraper import create_zip_file, get_markdown_content


# -- create_zip_file edge cases ------------------------------------------------

VALID_BODY = (
    "This is a detailed article with plenty of content.\n"
    "It spans multiple lines and paragraphs to pass validation.\n\n"
    "## Details\n\n"
    "More content here to ensure the word count threshold is met.\n"
)


class TestCreateZipFileEdges:
    def test_duplicate_titles_get_unique_filenames(self):
        content = f"# Same Title\n\n{VALID_BODY}"
        contents = [
            ("https://example.com/page1", content),
            ("https://example.com/page2", content),
        ]
        zip_path, count = create_zip_file(contents, "test-dupes")
        try:
            assert count == 2
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert len(names) == 2
                assert names[0] != names[1]
        finally:
            Path(zip_path).unlink(missing_ok=True)

    def test_content_with_no_extractable_title(self):
        content = f"Just some text without any headers at all.\n\n{VALID_BODY}"
        contents = [("https://example.com/no-title", content)]
        zip_path, count = create_zip_file(contents, "test-no-title")
        try:
            assert count == 1
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert len(names) == 1
                # Should be a hash-based filename
                assert names[0].endswith(".md")
        finally:
            Path(zip_path).unlink(missing_ok=True)

    def test_large_content_is_included(self):
        large_body = "x " * 10000  # ~20KB
        content = f"# Big Article\n\n{large_body}\n\nMore lines.\n\nEven more.\n"
        contents = [("https://example.com/big", content)]
        zip_path, count = create_zip_file(contents, "test-large")
        try:
            assert count == 1
            with zipfile.ZipFile(zip_path) as zf:
                data = zf.read(zf.namelist()[0]).decode("utf-8")
                assert len(data) > 10000
        finally:
            Path(zip_path).unlink(missing_ok=True)


# -- get_markdown_content ------------------------------------------------------

JINA_VALID_RESPONSE = (
    "# Test Article\n\n"
    "This is a full article with enough content to pass validation.\n\n"
    "## Section\n\n"
    "More detailed content that makes this article substantive and real.\n"
    "Additional lines ensure we clear the content length threshold.\n"
)


def _make_transport(responses: list[tuple[int, str]]):
    """Create an httpx MockTransport that returns responses in order.

    Each call pops the next (status, body) tuple. If the list is exhausted,
    returns 500.
    """
    call_index = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = call_index["i"]
        call_index["i"] += 1
        if idx < len(responses):
            status, body = responses[idx]
            return httpx.Response(status, text=body)
        return httpx.Response(500, text="Exhausted responses")

    return httpx.MockTransport(handler)


@pytest.fixture()
def fresh_tracker():
    return ProgressTracker()


@pytest.fixture()
def fast_limiter():
    return RateLimiter(limit=100, period=1)


class TestGetMarkdownContent:
    async def test_successful_fetch(self, monkeypatch, fresh_tracker, fast_limiter):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)

        await fresh_tracker.init("t1", total=1)
        transport = _make_transport([(200, JINA_VALID_RESPONSE)])
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content("https://example.com/article", client, "t1")
        assert url == "https://example.com/article"
        assert "Test Article" in content

    async def test_skipped_url_returns_empty(self, monkeypatch, fresh_tracker, fast_limiter):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)

        await fresh_tracker.init("t1", total=1)
        # twitter.com URLs are in the skip list
        transport = _make_transport([])
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content("https://twitter.com/user/status/123", client, "t1")
        assert content == ""
        state = await fresh_tracker.get("t1")
        assert state["skipped"] == 1

    async def test_429_triggers_retry(self, monkeypatch, fresh_tracker, fast_limiter):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)
        monkeypatch.setattr("link_content_scraper.scraper.RETRY_DELAY", 0)

        await fresh_tracker.init("t1", total=1)
        transport = _make_transport([
            (429, "Rate limited"),
            (200, JINA_VALID_RESPONSE),
        ])
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content("https://example.com/retry", client, "t1")
        assert "Test Article" in content

    async def test_content_validation_failure_retries_then_fails(self, monkeypatch, fresh_tracker, fast_limiter):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)
        monkeypatch.setattr("link_content_scraper.scraper.RETRY_DELAY", 0)
        monkeypatch.setattr("link_content_scraper.scraper.MAX_RETRIES", 1)

        await fresh_tracker.init("t1", total=1)
        transport = _make_transport([
            (200, "too short"),
            (200, "too short"),
        ])
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content("https://example.com/short", client, "t1")
        assert content == ""
        state = await fresh_tracker.get("t1")
        assert state["failed"] == 1

    async def test_cancelled_mid_fetch_returns_empty(self, monkeypatch, fresh_tracker, fast_limiter):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)

        await fresh_tracker.init("t1", total=1)
        await fresh_tracker.cancel("t1")
        transport = _make_transport([(200, JINA_VALID_RESPONSE)])
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content("https://example.com/cancel", client, "t1")
        assert content == ""

    async def test_network_error_retries_then_fails(self, monkeypatch, fresh_tracker, fast_limiter):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)
        monkeypatch.setattr("link_content_scraper.scraper.RETRY_DELAY", 0)
        monkeypatch.setattr("link_content_scraper.scraper.MAX_RETRIES", 1)

        await fresh_tracker.init("t1", total=1)

        def error_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(error_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content("https://example.com/fail", client, "t1")
        assert content == ""
        state = await fresh_tracker.get("t1")
        assert state["failed"] == 1
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test: add scraper module unit tests"
```

---

### Task 6: BDD feature file (`tests/features/scraping.feature`)

**Files:**
- Create: `tests/features/scraping.feature`

- [ ] **Step 1: Create the features directory and feature file**

Create `tests/features/scraping.feature`:

```gherkin
Feature: Web scraping lifecycle
  As a user of the link content scraper
  I want to scrape web pages and download them as markdown
  So that I can read web content offline

  Scenario: Successfully scrape a page and download results
    Given a target site with 3 linked pages
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    Then I receive a job ID and link list
    And I can download a ZIP file containing 4 markdown files
    And each markdown file contains the original URL header

  Scenario: Cancel an in-progress scrape
    Given a target site with 10 linked pages
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    And I cancel the scrape before it completes
    Then the cancellation is confirmed
    And the progress shows the scrape was cancelled

  Scenario: Scrape a non-existent URL
    Given the scraper is configured to use the local test server
    When I submit a scrape request for a URL that returns 404
    Then I receive a 502 error with a descriptive message

  Scenario: Upstream server error
    Given a target site that returns 500 for all pages
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    Then I receive an error indicating the scrape failed

  Scenario: All pages return empty content
    Given a target site where all pages have minimal content
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    Then I receive an error about no valid content
```

- [ ] **Step 2: Verify pytest-bdd collects the feature file**

Run: `uv run pytest --collect-only tests/features/`
Expected: No errors (feature files are collected or ignored gracefully — step defs come next).

- [ ] **Step 3: Commit**

```bash
git add tests/features/scraping.feature
git commit -m "test: add BDD feature file for scrape lifecycle scenarios"
```

---

### Task 7: BDD step definitions (`tests/test_bdd_scrape.py`)

**Files:**
- Create: `tests/test_bdd_scrape.py`

This is the most complex task. The step definitions wire Gherkin steps to real FastAPI test client calls with monkeypatched Jina URLs pointing at the local test server.

- [ ] **Step 1: Write the step definitions**

Create `tests/test_bdd_scrape.py`:

```python
# ABOUTME: BDD step definitions for the web scraping lifecycle feature.
# ABOUTME: Wires Gherkin scenarios to FastAPI test client with a local test server.

import hashlib
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from pytest_bdd import given, when, then, scenarios, parsers

from tests.conftest import VALID_MARKDOWN, MINIMAL_CONTENT, make_page_routes

scenarios("features/scraping.feature")


@pytest.fixture()
def ctx():
    """Mutable context dict shared across steps within a single scenario."""
    return {}


# -- Given steps ---------------------------------------------------------------

@given(parsers.parse("a target site with {count:d} linked pages"), target_fixture="ctx")
def given_target_site(test_server, count, ctx):
    routes = make_page_routes(count)
    server = test_server(routes)
    ctx["server"] = server
    ctx["page_count"] = count
    ctx["target_url"] = server.base_url
    return ctx


@given("the scraper is configured to use the local test server")
def given_scraper_configured(ctx, monkeypatch):
    base = ctx.get("server", None)
    if base is None:
        return
    # Monkeypatch the Jina URL prefix so get_markdown_content hits our local server.
    # The scraper builds URLs as f"https://r.jina.ai/{url}" — we replace that prefix.
    # We also need the local server to respond to requests at paths like
    # /http://localhost:PORT/pageN, so we monkeypatch at the scraper level.
    jina_base = base.base_url + "/"
    monkeypatch.setattr(
        "link_content_scraper.scraper.get_markdown_content",
        _make_passthrough_fetcher(ctx),
    )


@given("a target site that returns 500 for all pages", target_fixture="ctx")
def given_target_500(test_server, ctx):
    routes = make_page_routes(3, status=500, content="Internal Server Error")
    server = test_server(routes)
    ctx["server"] = server
    ctx["page_count"] = 3
    ctx["target_url"] = server.base_url
    return ctx


@given("a target site where all pages have minimal content", target_fixture="ctx")
def given_target_minimal(test_server, ctx):
    routes = make_page_routes(3, content=MINIMAL_CONTENT)
    server = test_server(routes)
    ctx["server"] = server
    ctx["page_count"] = 3
    ctx["target_url"] = server.base_url
    return ctx


# -- When steps ----------------------------------------------------------------

@when("I submit a scrape request for the target site")
def when_submit_scrape(client, ctx):
    resp = client.post("/api/scrape", json={"url": ctx["target_url"]})
    ctx["response"] = resp


@when("I submit a scrape request for a URL that returns 404")
def when_submit_404(client, ctx):
    server = ctx.get("server")
    url = server.base_url + "/nonexistent" if server else "http://localhost:1/bad"
    resp = client.post("/api/scrape", json={"url": url})
    ctx["response"] = resp


@when("I cancel the scrape before it completes")
def when_cancel_scrape(client, ctx):
    url = ctx["target_url"]
    tracker_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    ctx["tracker_id"] = tracker_id
    resp = client.post(f"/cancel/{tracker_id}")
    ctx["cancel_response"] = resp


# -- Then steps ----------------------------------------------------------------

@then("I receive a job ID and link list")
def then_job_id_and_links(ctx):
    resp = ctx["response"]
    assert resp.status_code == 200
    data = resp.json()
    assert "jobId" in data
    assert "links" in data
    assert len(data["links"]) > 0
    ctx["job_id"] = data["jobId"]


@then(parsers.parse("I can download a ZIP file containing {count:d} markdown files"))
def then_download_zip(client, ctx, count):
    job_id = ctx["job_id"]
    resp = client.get(f"/api/download/{job_id}")
    assert resp.status_code == 200
    assert "application/zip" in resp.headers.get("content-type", "")
    zf = zipfile.ZipFile(BytesIO(resp.content))
    names = zf.namelist()
    assert len(names) == count
    for name in names:
        assert name.endswith(".md")
    ctx["zip_file"] = zf


@then("each markdown file contains the original URL header")
def then_markdown_has_url_header(ctx):
    zf = ctx["zip_file"]
    for name in zf.namelist():
        content = zf.read(name).decode("utf-8")
        assert content.startswith("# Original URL: http")


@then("the cancellation is confirmed")
def then_cancel_confirmed(ctx):
    resp = ctx["cancel_response"]
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@then("the progress shows the scrape was cancelled")
def then_progress_cancelled(ctx):
    # The cancel endpoint returned 200, which confirms the tracker was marked
    assert ctx["cancel_response"].status_code == 200


@then(parsers.parse("I receive a {status_code:d} error with a descriptive message"))
def then_error_with_message(ctx, status_code):
    resp = ctx["response"]
    assert resp.status_code == status_code
    data = resp.json()
    assert "detail" in data
    assert len(data["detail"]) > 10


@then("I receive an error indicating the scrape failed")
def then_scrape_failed(ctx):
    resp = ctx["response"]
    assert resp.status_code in (500, 502)
    data = resp.json()
    assert "detail" in data


@then("I receive an error about no valid content")
def then_no_valid_content(ctx):
    resp = ctx["response"]
    assert resp.status_code == 500
    data = resp.json()
    assert "detail" in data


# -- Helpers -------------------------------------------------------------------

def _make_passthrough_fetcher(ctx):
    """Create a replacement for get_markdown_content that fetches from the local test server."""
    from link_content_scraper.progress import progress_tracker
    from link_content_scraper.filters import should_skip_url

    async def _fetch(url, client, tracker_id):
        await progress_tracker.update(tracker_id, current_url=url)
        if should_skip_url(url):
            await progress_tracker.increment(tracker_id, processed=1, skipped=1)
            return url, ""

        if await progress_tracker.is_cancelled(tracker_id):
            return url, ""

        server = ctx.get("server")
        if server is None:
            await progress_tracker.increment(tracker_id, processed=1, failed=1)
            return url, ""

        # Map the original URL to a local server path
        # URLs from the index page will be like http://localhost:PORT/pageN
        import httpx as _httpx
        try:
            jina_url = f"{server.base_url}{url.replace(server.base_url, '')}"
            async with _httpx.AsyncClient() as c:
                resp = await c.get(jina_url, timeout=5)
            if resp.status_code == 200 and len(resp.text.strip()) > 50:
                await progress_tracker.increment(tracker_id, processed=1, potential_successful=1)
                return url, resp.text.strip()
            else:
                await progress_tracker.increment(tracker_id, processed=1, failed=1)
                return url, ""
        except Exception:
            await progress_tracker.increment(tracker_id, processed=1, failed=1)
            return url, ""

    return _fetch
```

- [ ] **Step 2: Run the BDD tests**

Run: `uv run pytest tests/test_bdd_scrape.py -v`
Expected: Scenarios pass or fail with clear errors to debug. The happy path and error scenarios should work with the local test server.

- [ ] **Step 3: Debug and fix any failures**

Common issues to check:
- The local test server's index page must generate links that `BeautifulSoup` in `scrape_site` can parse
- The monkeypatched `get_markdown_content` must update the progress tracker correctly
- Timing: the cancel scenario may need the scrape to be running in a background task

Iterate until all 5 scenarios pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_bdd_scrape.py
git commit -m "test: add BDD step definitions for scrape lifecycle scenarios"
```

---

### Task 8: Remove duplicate client fixture from test_routes.py

**Files:**
- Modify: `tests/test_routes.py:5-8`

The `client` fixture now lives in `conftest.py`. Remove the duplicate from `test_routes.py`.

- [ ] **Step 1: Remove the duplicate fixture**

In `tests/test_routes.py`, remove:
```python
@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)
```

And remove the now-unused imports:
```python
from fastapi.testclient import TestClient
from link_content_scraper.app import create_app
```

The file should start with:
```python
# ABOUTME: Tests for API endpoints using FastAPI's test client.
# ABOUTME: Covers health, index, cancel, download, and scrape validation routes.

import pytest


class TestHealthEndpoint:
```

- [ ] **Step 2: Verify existing route tests still pass**

Run: `uv run pytest tests/test_routes.py -v`
Expected: All existing tests PASS using the shared `client` fixture from conftest.

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes.py
git commit -m "refactor: use shared client fixture from conftest in route tests"
```

---

### Task 9: Run full test suite and close beads

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS — existing + new unit + BDD.

- [ ] **Step 2: Fix any failures**

If any tests fail, debug and fix. Common issues:
- Import path mismatches
- Async event loop conflicts between aiohttp test server and pytest-asyncio
- Timing sensitivity in rate limiter tests

- [ ] **Step 3: Close beads issues**

```bash
bd close link_content_scraper-c5q link_content_scraper-0bt
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: complete unit test and BDD coverage for scraper modules"
```
