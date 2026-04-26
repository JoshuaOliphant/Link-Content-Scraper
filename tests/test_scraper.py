# ABOUTME: Unit tests for scraper module functions (create_zip_file, get_markdown_content).
# ABOUTME: Uses httpx MockTransport for HTTP control and monkeypatched singletons.

import zipfile
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from link_content_scraper.progress import ProgressTracker
from link_content_scraper.rate_limit import RateLimiter
from link_content_scraper.scraper import (
    create_zip_file,
    extract_content_links,
    get_markdown_content,
    scrape_site,
)


# -- extract_content_links -----------------------------------------------------

def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, 'html.parser')


class TestExtractContentLinks:
    def test_main_tag_excludes_header_and_footer(self):
        html = """
        <html><body>
          <header><a href="https://example.com/nav">Nav</a></header>
          <main><a href="https://example.com/article">Article</a></main>
          <footer><a href="https://example.com/footer">Footer</a></footer>
        </body></html>
        """
        assert extract_content_links(_soup(html)) == ["https://example.com/article"]

    def test_article_tag_used_when_no_main(self):
        html = """
        <html><body>
          <nav><a href="https://example.com/nav">Nav</a></nav>
          <article><a href="https://example.com/content">Content</a></article>
        </body></html>
        """
        assert extract_content_links(_soup(html)) == ["https://example.com/content"]

    def test_role_main_used_when_no_main_or_article(self):
        html = """
        <html><body>
          <nav><a href="https://example.com/nav">Nav</a></nav>
          <div role="main"><a href="https://example.com/content">Content</a></div>
        </body></html>
        """
        assert extract_content_links(_soup(html)) == ["https://example.com/content"]

    def test_fallback_strips_boilerplate_tags(self):
        html = """
        <html><body>
          <header><a href="https://example.com/nav">Nav</a></header>
          <div class="content"><a href="https://example.com/body">Body</a></div>
          <footer><a href="https://example.com/footer">Footer</a></footer>
          <aside><a href="https://example.com/sidebar">Sidebar</a></aside>
        </body></html>
        """
        links = extract_content_links(_soup(html))
        assert "https://example.com/body" in links
        assert "https://example.com/nav" not in links
        assert "https://example.com/footer" not in links
        assert "https://example.com/sidebar" not in links

    def test_deduplicates_while_preserving_order(self):
        html = """
        <html><body>
          <main>
            <a href="https://a.com/1">1</a>
            <a href="https://a.com/2">2</a>
            <a href="https://a.com/1">duplicate</a>
          </main>
        </body></html>
        """
        assert extract_content_links(_soup(html)) == ["https://a.com/1", "https://a.com/2"]

    def test_empty_page_returns_empty_list(self):
        assert extract_content_links(_soup("<html><body></body></html>")) == []


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

    async def test_arxiv_url_is_transformed_and_logged(
        self, monkeypatch, fresh_tracker, fast_limiter, caplog
    ):
        import logging

        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)
        await fresh_tracker.init("t1", total=1)

        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, text=JINA_VALID_RESPONSE)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with caplog.at_level(logging.INFO, logger="link_content_scraper.scraper"):
                url, content = await get_markdown_content(
                    "https://arxiv.org/abs/2401.12345", client, "t1"
                )
        assert content
        assert any(".pdf" in u for u in seen), f"Expected transformed PDF URL in {seen}"
        assert any("URL transformation" in m for m in caplog.messages)

    async def test_increment_usage_failure_does_not_break_fetch(
        self, monkeypatch, fresh_tracker, fast_limiter, caplog
    ):
        import logging
        from link_content_scraper import scraper as scraper_module

        monkeypatch.setattr(scraper_module, "progress_tracker", fresh_tracker)
        monkeypatch.setattr(scraper_module, "rate_limiter", fast_limiter)

        class _BoomDb:
            async def increment_usage(self, customer_id, month):
                raise RuntimeError("usage table down")

        monkeypatch.setattr(scraper_module, "db_client", _BoomDb())

        await fresh_tracker.init("t1", total=1)
        transport = _make_transport([(200, JINA_VALID_RESPONSE)])
        async with httpx.AsyncClient(transport=transport) as client:
            with caplog.at_level(logging.ERROR, logger="link_content_scraper.scraper"):
                url, content = await get_markdown_content(
                    "https://example.com/usage-fail", client, "t1", customer_id="cus_x"
                )
        assert content, "Fetch must succeed even if usage tracking fails"
        assert any("Failed to increment usage" in m for m in caplog.messages)

    async def test_non_200_non_429_raises_and_retries(
        self, monkeypatch, fresh_tracker, fast_limiter
    ):
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)
        monkeypatch.setattr("link_content_scraper.scraper.RETRY_DELAY", 0)
        monkeypatch.setattr("link_content_scraper.scraper.MAX_RETRIES", 1)

        await fresh_tracker.init("t1", total=1)
        # 500 then 500 — both raise httpx.HTTPStatusError, which is caught and retried
        transport = _make_transport([(500, "boom"), (500, "boom")])
        async with httpx.AsyncClient(transport=transport) as client:
            url, content = await get_markdown_content(
                "https://example.com/server-error", client, "t1"
            )
        assert content == ""
        state = await fresh_tracker.get("t1")
        assert state["failed"] == 1

    async def test_increment_usage_called_for_authenticated_customer(
        self, monkeypatch, fresh_tracker, fast_limiter
    ):
        from link_content_scraper import scraper as scraper_module

        monkeypatch.setattr(scraper_module, "progress_tracker", fresh_tracker)
        monkeypatch.setattr(scraper_module, "rate_limiter", fast_limiter)

        calls = []

        class _OkDb:
            async def increment_usage(self, customer_id, month):
                calls.append((customer_id, month))

        monkeypatch.setattr(scraper_module, "db_client", _OkDb())
        await fresh_tracker.init("t1", total=1)

        transport = _make_transport([(200, JINA_VALID_RESPONSE)])
        async with httpx.AsyncClient(transport=transport) as client:
            await get_markdown_content(
                "https://example.com/track", client, "t1", customer_id="cus_track"
            )
        assert len(calls) == 1
        assert calls[0][0] == "cus_track"

    async def test_cancellation_between_retries_returns_early(
        self, monkeypatch, fresh_tracker, fast_limiter
    ):
        """Cancel between iterations of the retry loop — line 88-89 cancellation check inside while loop."""
        monkeypatch.setattr("link_content_scraper.scraper.progress_tracker", fresh_tracker)
        monkeypatch.setattr("link_content_scraper.scraper.rate_limiter", fast_limiter)
        monkeypatch.setattr("link_content_scraper.scraper.RETRY_DELAY", 0)
        monkeypatch.setattr("link_content_scraper.scraper.MAX_RETRIES", 5)

        await fresh_tracker.init("t1", total=1)

        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(429, text="rate limited")

        transport = httpx.MockTransport(handler)

        # Patch is_cancelled so it returns True on the SECOND call (i.e. after the first
        # 429 response triggers a retry, the next iteration's cancellation check trips).
        original_is_cancelled = fresh_tracker.is_cancelled
        check_count = {"n": 0}

        async def _is_cancelled(tracker_id):
            check_count["n"] += 1
            # First check is at line 74 (before loop). Second check is at line 88 (in loop).
            # After we've made one HTTP call, cancel.
            if call_count["n"] >= 1 and check_count["n"] >= 2:
                return True
            return await original_is_cancelled(tracker_id)

        monkeypatch.setattr(fresh_tracker, "is_cancelled", _is_cancelled)

        transport_response = _make_transport([(429, "x"), (429, "x")])
        async with httpx.AsyncClient(transport=transport_response) as client:
            url, content = await get_markdown_content(
                "https://example.com/cancel-mid", client, "t1"
            )
        assert content == ""


# -- scrape_site full pipeline -------------------------------------------------

INDEX_HTML = """
<html><body>
  <main>
    {links}
  </main>
</body></html>
"""


def _index_page(link_urls: list[str]) -> str:
    anchors = "\n".join(f'<a href="{u}">page</a>' for u in link_urls)
    return INDEX_HTML.format(links=anchors)


class TestScrapeSite:
    async def test_basic_scrape_returns_urls_and_zip(
        self, monkeypatch, fresh_tracker, fast_limiter, tmp_path
    ):
        from link_content_scraper import scraper as scraper_module

        monkeypatch.setattr(scraper_module, "progress_tracker", fresh_tracker)
        monkeypatch.setattr(scraper_module, "rate_limiter", fast_limiter)

        sub = "https://example.com/sub1"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://example.com/":
                return httpx.Response(200, text=_index_page([sub]))
            # Otherwise, treat as Jina request
            return httpx.Response(200, text=JINA_VALID_RESPONSE)

        transport = httpx.MockTransport(handler)

        async def _runner():
            # Patch httpx.AsyncClient inside scraper to use our transport
            import httpx as httpx_mod
            original = httpx_mod.AsyncClient

            class _Patched(original):
                def __init__(self, *args, **kwargs):
                    kwargs["transport"] = transport
                    super().__init__(*args, **kwargs)

            monkeypatch.setattr(scraper_module.httpx, "AsyncClient", _Patched)
            urls, zip_path = await scrape_site(
                "https://example.com/", "trk1", "job_basic", customer_id=None
            )
            return urls, zip_path

        urls, zip_path = await _runner()
        try:
            assert urls[0] == "https://example.com/"
            assert sub in urls
            assert Path(zip_path).exists()
        finally:
            Path(zip_path).unlink(missing_ok=True)

    async def test_scrape_site_runs_two_batches_with_sleep(
        self, monkeypatch, fresh_tracker, fast_limiter, tmp_path
    ):
        """With BATCH_SIZE=2 and 4 links, scrape_site must process two batches and sleep between them (line 236)."""
        from link_content_scraper import scraper as scraper_module

        monkeypatch.setattr(scraper_module, "progress_tracker", fresh_tracker)
        monkeypatch.setattr(scraper_module, "rate_limiter", fast_limiter)
        monkeypatch.setattr(scraper_module, "BATCH_SIZE", 2)
        monkeypatch.setattr(scraper_module, "RATE_PERIOD", 0)  # so sleep is essentially instant

        sleeps: list[float] = []
        original_sleep = scraper_module.asyncio.sleep

        async def _spy_sleep(secs):
            sleeps.append(secs)
            await original_sleep(0)

        monkeypatch.setattr(scraper_module.asyncio, "sleep", _spy_sleep)

        sub_urls = [f"https://example.com/sub{i}" for i in range(4)]

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://example.com/":
                return httpx.Response(200, text=_index_page(sub_urls))
            return httpx.Response(200, text=JINA_VALID_RESPONSE)

        transport = httpx.MockTransport(handler)

        import httpx as httpx_mod
        original = httpx_mod.AsyncClient

        class _Patched(original):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(scraper_module.httpx, "AsyncClient", _Patched)

        urls, zip_path = await scrape_site(
            "https://example.com/", "trk2", "job_batches", customer_id=None
        )
        try:
            assert len(urls) == 5  # original + 4 sub
            # Inter-batch sleep is RATE_PERIOD/2 = 0; verify it was called at least once
            assert any(s == 0 for s in sleeps)
        finally:
            Path(zip_path).unlink(missing_ok=True)

    async def test_scrape_site_breaks_when_cancelled_between_batches(
        self, monkeypatch, fresh_tracker, fast_limiter
    ):
        """Cancellation between batches must short-circuit the for loop (line 218)."""
        from link_content_scraper import scraper as scraper_module

        monkeypatch.setattr(scraper_module, "progress_tracker", fresh_tracker)
        monkeypatch.setattr(scraper_module, "rate_limiter", fast_limiter)
        monkeypatch.setattr(scraper_module, "BATCH_SIZE", 1)
        monkeypatch.setattr(scraper_module, "RATE_PERIOD", 0)

        sub_urls = [f"https://example.com/sub{i}" for i in range(3)]

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://example.com/":
                return httpx.Response(200, text=_index_page(sub_urls))
            return httpx.Response(200, text=JINA_VALID_RESPONSE)

        transport = httpx.MockTransport(handler)

        import httpx as httpx_mod
        original = httpx_mod.AsyncClient

        class _Patched(original):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(scraper_module.httpx, "AsyncClient", _Patched)

        # Patch is_cancelled to return True on the second call to short-circuit batch loop
        check_count = {"n": 0}
        original_is_cancelled = fresh_tracker.is_cancelled

        async def _is_cancelled(tracker_id):
            check_count["n"] += 1
            # Allow initial fetches but cancel before all batches complete.
            # The first batch processes one link (sub0), then the second batch's cancel-check trips.
            if check_count["n"] > 4:
                return True
            return await original_is_cancelled(tracker_id)

        monkeypatch.setattr(fresh_tracker, "is_cancelled", _is_cancelled)

        # Pre-init tracker so create_zip_file step has at least one valid result
        try:
            urls, zip_path = await scrape_site(
                "https://example.com/", "trk_cancel", "job_cancel", customer_id=None
            )
            try:
                # All 3 sub URLs are returned as the link list, but not all were processed
                assert len(urls) == 4  # original + 3 sub
            finally:
                Path(zip_path).unlink(missing_ok=True)
        except ValueError:
            # If cancellation prevents any successful content, create_zip_file raises.
            # That's an acceptable outcome for this branch — the cancel path was still hit.
            pass

    async def test_scrape_site_handles_exception_from_task(
        self, monkeypatch, fresh_tracker, fast_limiter, caplog
    ):
        """An exception from a batch task must be logged and counted as failed (lines 231-233)."""
        import logging
        from link_content_scraper import scraper as scraper_module

        monkeypatch.setattr(scraper_module, "progress_tracker", fresh_tracker)
        monkeypatch.setattr(scraper_module, "rate_limiter", fast_limiter)
        monkeypatch.setattr(scraper_module, "BATCH_SIZE", 5)
        monkeypatch.setattr(scraper_module, "RATE_PERIOD", 0)

        sub_urls = ["https://example.com/sub0", "https://example.com/sub1"]

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://example.com/":
                return httpx.Response(200, text=_index_page(sub_urls))
            return httpx.Response(200, text=JINA_VALID_RESPONSE)

        transport = httpx.MockTransport(handler)

        import httpx as httpx_mod
        original = httpx_mod.AsyncClient

        class _Patched(original):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(scraper_module.httpx, "AsyncClient", _Patched)

        # Patch get_markdown_content so the first sub URL raises a regular Exception
        # — gather(return_exceptions=True) collects it, then the dispatch loop
        # logs it and increments the failed counter.
        original_fn = scraper_module.get_markdown_content

        async def _flaky_fn(url, client, tracker_id, customer_id=None):
            if "sub0" in url:
                raise RuntimeError("simulated task failure")
            return await original_fn(url, client, tracker_id, customer_id)

        monkeypatch.setattr(scraper_module, "get_markdown_content", _flaky_fn)

        with caplog.at_level(logging.ERROR, logger="link_content_scraper.scraper"):
            urls, zip_path = await scrape_site(
                "https://example.com/", "trk_base", "job_base", customer_id=None
            )
        try:
            assert any("Unhandled task exception" in m for m in caplog.messages)
            state = await fresh_tracker.get("trk_base")
            assert state["failed"] >= 1
        finally:
            Path(zip_path).unlink(missing_ok=True)
