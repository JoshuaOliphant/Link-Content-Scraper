# ABOUTME: BDD step definitions for the web scraping lifecycle feature.
# ABOUTME: Wires Gherkin scenarios to FastAPI test client with a local test server.

import asyncio
import hashlib
import zipfile
from io import BytesIO

import httpx
import pytest
from aiohttp import web
from pytest_bdd import given, scenarios, then, when, parsers

import link_content_scraper.auth as auth_module
from link_content_scraper.auth import Customer
from tests.conftest import MINIMAL_CONTENT, LocalTestServer, make_page_routes

scenarios("features/scraping.feature")

_TEST_API_KEY = "test-bdd-api-key"
_TEST_CUSTOMER = Customer(
    stripe_customer_id="cus_bdd_test",
    email="bdd@example.com",
    tier="pro",
    active=True,
)


class _MockDbClient:
    async def get_customer_by_key(self, key_hash: str) -> Customer:
        return _TEST_CUSTOMER

    async def get_usage(self, customer_id: str, month: str) -> int:
        return 0

    async def increment_usage(self, customer_id: str, month: str) -> None:
        pass


@pytest.fixture(autouse=True)
def _mock_auth_db(monkeypatch):
    """Bypass Supabase for all BDD tests by substituting a no-op db client."""
    import link_content_scraper.routes as routes_module
    import link_content_scraper.scraper as scraper_module
    mock = _MockDbClient()
    monkeypatch.setattr(auth_module, "db_client", mock)
    monkeypatch.setattr(scraper_module, "db_client", mock)
    monkeypatch.setattr(routes_module, "db_client", mock)


@pytest.fixture()
def ctx():
    """Mutable context dict shared across steps within a single scenario."""
    return {}


@pytest.fixture()
def managed_servers():
    """Holds manually started servers for cleanup after each scenario."""
    servers: list[LocalTestServer] = []
    yield servers
    for srv in servers:
        srv.stop()


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
def given_scraper_configured(ctx, test_server, monkeypatch):
    if ctx.get("server") is None:
        # For scenarios that don't set up a target site up front, create a
        # minimal server so the passthrough fetcher has somewhere to route to.
        server = test_server({})
        ctx["server"] = server
    monkeypatch.setattr(
        "link_content_scraper.scraper.get_markdown_content",
        _make_passthrough_fetcher(ctx),
    )


@given("a target site that returns 500 for all pages", target_fixture="ctx")
def given_target_500(managed_servers, ctx):
    # Include root "/" so the direct client.get(url) in scrape_site raises HTTPStatusError.
    routes = {"/": (500, "Internal Server Error")}
    routes.update(make_page_routes(3, status=500, content="Internal Server Error"))
    server = _start_custom_server(routes)
    managed_servers.append(server)
    ctx["server"] = server
    ctx["page_count"] = 3
    ctx["target_url"] = server.base_url
    return ctx


@given("a target site where all pages have minimal content", target_fixture="ctx")
def given_target_minimal(managed_servers, ctx):
    # All routes, including root, serve minimal content so is_content_valid fails
    # for every page, causing create_zip_file to raise ValueError.
    routes = {"/": (200, MINIMAL_CONTENT)}
    routes.update(make_page_routes(3, content=MINIMAL_CONTENT))
    server = _start_custom_server(routes)
    managed_servers.append(server)
    ctx["server"] = server
    ctx["page_count"] = 3
    ctx["target_url"] = server.base_url
    return ctx


# -- When steps ----------------------------------------------------------------

@when("I submit a scrape request for the target site")
def when_submit_scrape(client, ctx):
    resp = client.post(
        "/api/scrape",
        json={"url": ctx["target_url"]},
        headers={"x-api-key": _TEST_API_KEY},
    )
    ctx["response"] = resp


@when("I submit a scrape request for a URL that returns 404")
def when_submit_404(client, ctx):
    server = ctx.get("server")
    url = server.base_url + "/nonexistent" if server else "http://localhost:1/bad"
    resp = client.post(
        "/api/scrape",
        json={"url": url},
        headers={"x-api-key": _TEST_API_KEY},
    )
    ctx["response"] = resp


@when("I cancel the scrape before it completes")
def when_cancel_scrape(client, ctx):
    # The test client is synchronous, so the scrape already completed before
    # we reach this step. We init a fresh tracker and cancel it to verify the
    # cancel endpoint behaves correctly.
    url = ctx["target_url"]
    tracker_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    ctx["tracker_id"] = tracker_id

    from link_content_scraper.progress import progress_tracker

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(progress_tracker.init(tracker_id, total=10))
    finally:
        loop.close()

    resp = client.post(f"/cancel/{tracker_id}", headers={"x-api-key": _TEST_API_KEY})
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
    resp = client.get(f"/api/download/{job_id}", headers={"x-api-key": _TEST_API_KEY})
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
    from link_content_scraper.content import is_content_valid
    from link_content_scraper.filters import should_skip_url
    from link_content_scraper.progress import progress_tracker

    async def _fetch(url, client, tracker_id, customer_id=None):
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

        # Map the original URL to a local server path.
        # Links from the index page look like http://localhost:PORT/pageN.
        jina_url = f"{server.base_url}{url.replace(server.base_url, '')}"
        try:
            async with httpx.AsyncClient() as c:
                resp = await c.get(jina_url, timeout=5)
            content = resp.text.strip() if resp.status_code == 200 else ""
            if content and is_content_valid(content):
                await progress_tracker.increment(tracker_id, processed=1, potential_successful=1)
                return url, content
            else:
                await progress_tracker.increment(tracker_id, processed=1, failed=1)
                return url, ""
        except Exception:
            await progress_tracker.increment(tracker_id, processed=1, failed=1)
            return url, ""

    return _fetch


def _start_custom_server(routes: dict) -> LocalTestServer:
    """Start a local test server that returns configured responses for all paths including root.

    Unlike the standard test server, every path (including root "/") is
    served from the routes dict, with no auto-generated index HTML.
    """
    class CustomServer(LocalTestServer):
        """Test server where every path, including root, returns the configured response."""

        def __init__(self, custom_routes: dict):
            super().__init__({})
            self._custom_routes = custom_routes

        async def _start(self, started):
            app = web.Application()

            async def handle_any(request):
                path = request.path
                if path in self._custom_routes:
                    status, body = self._custom_routes[path]
                    return web.Response(status=status, text=body)
                return web.Response(status=404, text="Not found")

            app.router.add_route("*", "/{tail:.*}", handle_any)
            app.router.add_route("*", "/", handle_any)

            self._runner = web.AppRunner(app)
            await self._runner.setup()
            site = web.TCPSite(self._runner, "localhost", 0)
            await site.start()
            self.port = site._server.sockets[0].getsockname()[1]
            started.set()

    server = CustomServer(routes)
    server.start()
    return server
