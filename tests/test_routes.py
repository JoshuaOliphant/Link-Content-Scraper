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


class TestScrapeResponseIncludesTrackerId:
    """Task link_content_scraper-zmq: scrape response must expose tracker_id so callers can cancel."""

    def _setup_auth_mock(self, monkeypatch):
        import link_content_scraper.auth as auth_module
        from link_content_scraper.auth import Customer

        _customer = Customer(stripe_customer_id="cus_test", email="t@t.com", tier="pro", active=True)

        class _MockDb:
            async def get_customer_by_key(self, key_hash):
                return _customer

            async def get_usage(self, customer_id, month):
                return 0

        monkeypatch.setattr(auth_module, "db_client", _MockDb())

    def test_scrape_response_contains_tracker_id(self, client, monkeypatch, tmp_path):
        """POST /api/scrape response must include tracker_id derived from the URL."""
        import hashlib
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        test_url = "http://example.com/test-page"
        expected_tracker_id = hashlib.sha256(test_url.encode("utf-8")).hexdigest()[:16]

        # Create a dummy zip file for the mock to return
        zip_file = tmp_path / "job.zip"
        zip_file.write_bytes(b"PK\x03\x04")

        async def _mock_scrape_site(url, tracker_id, job_id, customer_id):
            return (["http://example.com/test-page"], str(zip_file))

        monkeypatch.setattr(routes_module, "scrape_site", _mock_scrape_site)

        resp = client.post(
            "/api/scrape",
            json={"url": test_url},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "trackerId" in data, "Response must include trackerId"
        assert data["trackerId"] == expected_tracker_id

    def test_tracker_id_matches_cancel_endpoint_format(self, client, monkeypatch, tmp_path):
        """tracker_id in the scrape response must be usable with POST /cancel/{tracker_id}."""
        import link_content_scraper.routes as routes_module
        from link_content_scraper.progress import progress_tracker
        import asyncio

        self._setup_auth_mock(monkeypatch)

        test_url = "http://example.com/cancel-test"

        zip_file = tmp_path / "job.zip"
        zip_file.write_bytes(b"PK\x03\x04")

        async def _mock_scrape_site(url, tracker_id, job_id, customer_id):
            # Register the tracker so cancel can find it
            await progress_tracker.init(tracker_id, total=1, processed=1)
            return (["http://example.com/cancel-test"], str(zip_file))

        monkeypatch.setattr(routes_module, "scrape_site", _mock_scrape_site)

        resp = client.post(
            "/api/scrape",
            json={"url": test_url},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 200
        tracker_id = resp.json()["trackerId"]

        # Re-init the tracker since the scrape endpoint removes it after completion
        loop = asyncio.new_event_loop()
        loop.run_until_complete(progress_tracker.init(tracker_id, total=1))
        loop.close()

        cancel_resp = client.post(f"/cancel/{tracker_id}")
        assert cancel_resp.status_code == 200


class TestBillingStatus:
    """Task link_content_scraper-3ki: GET /api/billing/status returns tier, usage, limit, month."""

    def _make_auth_mock(self, monkeypatch, tier="pro", usage=42):
        import link_content_scraper.auth as auth_module
        import link_content_scraper.routes as routes_module
        from link_content_scraper.auth import Customer

        _customer = Customer(
            stripe_customer_id="cus_test",
            email="t@t.com",
            tier=tier,
            active=True,
        )

        class _MockDb:
            async def get_customer_by_key(self, key_hash):
                return _customer

            async def get_usage(self, customer_id, month):
                return usage

        mock_db = _MockDb()
        monkeypatch.setattr(auth_module, "db_client", mock_db)
        monkeypatch.setattr(routes_module, "db_client", mock_db)
        return _customer

    def test_billing_status_returns_tier_and_usage(self, client, monkeypatch):
        """Response must include tier, usage, limit, and month fields."""
        from datetime import UTC, datetime

        customer = self._make_auth_mock(monkeypatch, tier="pro", usage=42)

        resp = client.get("/api/billing/status", headers={"x-api-key": "test-key"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"
        assert data["usage"] == 42
        assert data["limit"] == 25_000  # pro limit from TIER_LIMITS
        assert data["month"] == datetime.now(UTC).strftime("%Y-%m")

    def test_billing_status_requires_auth(self, client):
        """Endpoint must return 401 when no API key is provided."""
        resp = client.get("/api/billing/status")
        assert resp.status_code == 401

    def test_billing_status_free_tier_limit(self, client, monkeypatch):
        """Free tier limit is 100 URLs per month."""
        self._make_auth_mock(monkeypatch, tier="free", usage=10)

        resp = client.get("/api/billing/status", headers={"x-api-key": "test-key"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["limit"] == 100


class TestSSEEventSchema:
    """Task link_content_scraper-8io: SSE events must include all required fields."""

    _REQUIRED_FIELDS = {"processed", "total", "current_url", "successful", "skipped", "failed"}

    def _parse_sse_events(self, raw_text: str) -> list[dict]:
        """Parse raw SSE text into a list of event dicts."""
        import json

        events = []
        for block in raw_text.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            for line in block.splitlines():
                if line.startswith("data: "):
                    payload = line[len("data: "):]
                    try:
                        events.append(json.loads(payload))
                    except Exception:
                        pass
        return events

    def test_progress_event_has_all_required_fields(self, client):
        """In-progress SSE events must include all 6 BDD-required fields."""
        import asyncio
        import hashlib
        from link_content_scraper.progress import progress_tracker

        test_url = "http://example.com/sse-test"
        tracker_id = hashlib.sha256(test_url.encode("utf-8")).hexdigest()[:16]

        # Init the tracker as partially done so generate_events emits a progress event
        loop = asyncio.new_event_loop()
        loop.run_until_complete(progress_tracker.init(tracker_id, total=5, processed=2))
        loop.close()

        # Immediately cancel so the stream terminates quickly
        loop2 = asyncio.new_event_loop()
        loop2.run_until_complete(progress_tracker.cancel(tracker_id))
        loop2.close()

        with client.stream("GET", f"/api/scrape/progress?url={test_url}") as resp:
            assert resp.status_code == 200
            resp.read()
            raw = resp.text

        events = self._parse_sse_events(raw)
        assert events, "Expected at least one SSE event"

        for event in events:
            if "error" in event:
                # Error events are a distinct type; skip field check
                continue
            for field in self._REQUIRED_FIELDS:
                assert field in event, f"SSE event missing required field '{field}': {event}"

    def test_final_event_has_all_required_fields(self, client):
        """The final (completion) SSE event must include all 6 BDD-required fields."""
        import asyncio
        import hashlib
        from link_content_scraper.progress import progress_tracker

        test_url = "http://example.com/sse-final-test"
        tracker_id = hashlib.sha256(test_url.encode("utf-8")).hexdigest()[:16]

        # Init tracker as fully complete — generate_events will emit the final event and stop
        loop = asyncio.new_event_loop()
        loop.run_until_complete(progress_tracker.init(tracker_id, total=3, processed=3))
        loop.run_until_complete(progress_tracker.update(tracker_id, successful=2, skipped=0, failed=1))
        loop.close()

        with client.stream("GET", f"/api/scrape/progress?url={test_url}") as resp:
            resp.read()
            raw = resp.text

        events = self._parse_sse_events(raw)
        assert events, "Expected at least one SSE event (final)"

        final = events[-1]
        for field in self._REQUIRED_FIELDS:
            assert field in final, f"Final SSE event missing required field '{field}': {final}"
