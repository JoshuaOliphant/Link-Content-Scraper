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
def client(monkeypatch):
    """FastAPI test client fixture with minimal config patched for startup guard."""
    import link_content_scraper.config as cfg
    monkeypatch.setattr(cfg, "STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setattr(cfg, "STRIPE_SECRET_KEY", "sk_test_fake")
    app = create_app()
    return TestClient(app)
