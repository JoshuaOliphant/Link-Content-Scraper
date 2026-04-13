# ABOUTME: Tests for API endpoints using FastAPI's test client.
# ABOUTME: Covers health, index, cancel, download, and scrape validation routes.

import pytest
from fastapi.testclient import TestClient

from link_content_scraper.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestIndexEndpoint:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Link Scraper" in resp.text


class TestCancelEndpoint:
    def test_cancel_unknown_tracker(self, client):
        resp = client.post("/cancel/nonexistent")
        assert resp.status_code == 404

    def test_cancel_existing_tracker(self, client):
        import asyncio
        from link_content_scraper.progress import progress_tracker

        loop = asyncio.new_event_loop()
        loop.run_until_complete(progress_tracker.init("test123", total=10))

        resp = client.post("/cancel/test123")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        loop.run_until_complete(progress_tracker.remove("test123"))
        loop.close()


class TestDownloadEndpoint:
    def test_download_missing_job(self, client):
        resp = client.get("/api/download/nonexistent")
        assert resp.status_code == 404


class TestScrapeValidation:
    def test_invalid_url(self, client):
        resp = client.post("/api/scrape", json={"url": "not-a-url"})
        assert resp.status_code == 422
