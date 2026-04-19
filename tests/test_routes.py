# ABOUTME: Tests for API endpoints using FastAPI's test client.
# ABOUTME: Covers health, index, cancel, download, and scrape validation routes.

import pytest


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
    def test_invalid_url(self, client, monkeypatch):
        import link_content_scraper.auth as auth_module
        from link_content_scraper.auth import Customer

        _customer = Customer(stripe_customer_id="cus_test", email="t@t.com", tier="pro", active=True)

        class _MockDb:
            async def get_customer_by_key(self, key_hash):
                return _customer

            async def get_usage(self, customer_id, month):
                return 0

        monkeypatch.setattr(auth_module, "db_client", _MockDb())
        resp = client.post("/api/scrape", json={"url": "not-a-url"}, headers={"x-api-key": "test-key"})
        assert resp.status_code == 422
