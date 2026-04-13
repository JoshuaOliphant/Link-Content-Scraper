# ABOUTME: Unit tests for scraper module functions (create_zip_file, get_markdown_content).
# ABOUTME: Uses httpx MockTransport for HTTP control and monkeypatched singletons.

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
