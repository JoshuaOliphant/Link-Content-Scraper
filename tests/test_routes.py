# ABOUTME: Tests for API endpoints using FastAPI's test client.
# ABOUTME: Covers health, index, cancel, download, and scrape validation routes.

import pytest
from link_content_scraper.auth import Customer


def _make_auth_mock(monkeypatch, customer=None):
    """Helper: patch db_client in auth and routes to return a specific customer."""
    import link_content_scraper.auth as auth_module
    import link_content_scraper.routes as routes_module

    if customer is None:
        customer = Customer(stripe_customer_id="cus_test", email="t@t.com", tier="pro", active=True)

    class _MockDb:
        async def get_customer_by_key(self, key_hash):
            return customer

        async def get_usage(self, customer_id, month):
            return 0

        async def claim_pending_key(self, session_id, email):
            return None

    mock = _MockDb()
    monkeypatch.setattr(auth_module, "db_client", mock)
    monkeypatch.setattr(routes_module, "db_client", mock)
    return mock


class TestHealthEndpoint:
    def test_health_ok_when_config_set(self, client, monkeypatch):
        """Health returns 200 when all required config is set."""
        import link_content_scraper.config as cfg
        monkeypatch.setattr(cfg, "SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setattr(cfg, "SUPABASE_KEY", "test_key")
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_reports_missing_supabase_url(self, client, monkeypatch):
        """Health returns 500 when SUPABASE_URL is not configured."""
        import link_content_scraper.config as cfg
        monkeypatch.setattr(cfg, "SUPABASE_URL", "")
        monkeypatch.setattr(cfg, "SUPABASE_KEY", "test_key")
        resp = client.get("/health")
        assert resp.status_code == 500
        assert any("SUPABASE_URL" in issue for issue in resp.json()["issues"])

    def test_health_reports_missing_supabase_key(self, client, monkeypatch):
        """Health returns 500 when SUPABASE_KEY is not configured."""
        import link_content_scraper.config as cfg
        monkeypatch.setattr(cfg, "SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setattr(cfg, "SUPABASE_KEY", "")
        resp = client.get("/health")
        assert resp.status_code == 500
        assert any("SUPABASE_KEY" in issue for issue in resp.json()["issues"])


class TestIndexEndpoint:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Link Scraper" in resp.text


class TestCancelEndpoint:
    def test_cancel_requires_auth(self, client):
        """Cancel endpoint must return 401 without an API key."""
        resp = client.post("/cancel/nonexistent")
        assert resp.status_code == 401

    def test_cancel_unknown_tracker_returns_404(self, client, monkeypatch):
        """Cancel returns 404 when tracker doesn't exist (with valid auth)."""
        _make_auth_mock(monkeypatch)
        resp = client.post("/cancel/nonexistent", headers={"x-api-key": "test-key"})
        assert resp.status_code == 404

    def test_cancel_existing_tracker(self, client, monkeypatch):
        import asyncio
        from link_content_scraper.progress import progress_tracker
        import link_content_scraper.routes as routes_module

        _make_auth_mock(monkeypatch)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(progress_tracker.init("test123", total=10))
        # Register ownership so cancel can verify
        routes_module._tracker_owners["test123"] = "cus_test"

        resp = client.post("/cancel/test123", headers={"x-api-key": "test-key"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        loop.run_until_complete(progress_tracker.remove("test123"))
        loop.close()

    def test_cancel_by_different_customer_returns_403(self, client, monkeypatch):
        """Cancel must return 403 when a different customer tries to cancel someone else's job."""
        import asyncio
        from link_content_scraper.progress import progress_tracker
        import link_content_scraper.routes as routes_module

        _make_auth_mock(monkeypatch)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(progress_tracker.init("tracker_other", total=10))
        routes_module._tracker_owners["tracker_other"] = "cus_different"

        resp = client.post("/cancel/tracker_other", headers={"x-api-key": "test-key"})
        assert resp.status_code == 403

        loop.run_until_complete(progress_tracker.remove("tracker_other"))
        loop.close()


class TestDownloadEndpoint:
    def test_download_requires_auth(self, client):
        """Download endpoint must return 401 without an API key."""
        resp = client.get("/api/download/nonexistent")
        assert resp.status_code == 401

    def test_download_missing_job_returns_404(self, client, monkeypatch):
        """Download returns 404 when job_id doesn't exist (with valid auth)."""
        _make_auth_mock(monkeypatch)
        resp = client.get("/api/download/nonexistent", headers={"x-api-key": "test-key"})
        assert resp.status_code == 404

    def test_download_by_different_customer_returns_404(self, client, monkeypatch, tmp_path):
        """Download must return 404 when a different customer tries to download someone else's job."""
        import link_content_scraper.routes as routes_module

        _make_auth_mock(monkeypatch)
        zip_file = tmp_path / "job.zip"
        zip_file.write_bytes(b"PK\x03\x04")
        routes_module._results["job_other"] = {"zip_path": str(zip_file), "customer_id": "cus_different"}

        resp = client.get("/api/download/job_other", headers={"x-api-key": "test-key"})
        assert resp.status_code == 404

        routes_module._results.pop("job_other", None)


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

        cancel_resp = client.post(f"/cancel/{tracker_id}", headers={"x-api-key": "test-key"})
        assert cancel_resp.status_code == 200


class TestFreeSignup:
    """Tests for POST /api/signup/free — email-only free tier provisioning."""

    def _setup_db_mock(self, monkeypatch):
        import link_content_scraper.auth as auth_module
        import link_content_scraper.routes as routes_module

        class _MockDb:
            def __init__(self):
                self.customers = {}
                self.api_keys = {}
                self.pending_keys = {}

            async def get_customer_by_key(self, key_hash):
                return None

            async def get_usage(self, customer_id, month):
                return 0

            async def get_customer_by_email(self, email):
                for cid, data in self.customers.items():
                    if data["email"] == email:
                        from link_content_scraper.auth import Customer
                        return Customer(stripe_customer_id=cid, email=email, tier=data["tier"], active=True)
                return None

            async def create_customer(self, customer_id, email, tier):
                self.customers[customer_id] = {"email": email, "tier": tier}

            async def create_api_key(self, key_hash, customer_id):
                self.api_keys[key_hash] = customer_id

            async def store_pending_key(self, session_id, raw_key, email, ttl_hours=24):
                self.pending_keys[session_id] = {"raw_key": raw_key, "email": email}

            async def claim_pending_key(self, session_id, email):
                entry = self.pending_keys.get(session_id)
                if entry is None or entry["email"] != email:
                    return None
                return self.pending_keys.pop(session_id)["raw_key"]

            async def delete_customer(self, customer_id):
                self.customers.pop(customer_id, None)

        mock = _MockDb()
        monkeypatch.setattr(auth_module, "db_client", mock)
        monkeypatch.setattr(routes_module, "db_client", mock)
        return mock

    def test_free_signup_requires_email(self, client):
        """POST /api/signup/free without email must return 422."""
        resp = client.post("/api/signup/free", json={})
        assert resp.status_code == 422

    def test_free_signup_creates_customer_and_returns_redirect(self, client, monkeypatch):
        """POST /api/signup/free with valid email creates a free customer and returns a redirect URL."""
        mock = self._setup_db_mock(monkeypatch)
        resp = client.post("/api/signup/free", json={"email": "free@example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert "redirectUrl" in data
        assert "session_id" in data["redirectUrl"]
        assert "email" in data["redirectUrl"]
        assert len(mock.customers) == 1
        assert len(mock.api_keys) == 1
        assert len(mock.pending_keys) == 1

    def test_free_signup_customer_has_free_tier(self, client, monkeypatch):
        """Free signup must create a customer with tier='free'."""
        mock = self._setup_db_mock(monkeypatch)
        client.post("/api/signup/free", json={"email": "free@example.com"})
        customer = list(mock.customers.values())[0]
        assert customer["tier"] == "free"

    def test_free_signup_customer_id_starts_with_free(self, client, monkeypatch):
        """Free customer ID must start with 'free_' to distinguish from Stripe customers."""
        mock = self._setup_db_mock(monkeypatch)
        client.post("/api/signup/free", json={"email": "free@example.com"})
        customer_id = list(mock.customers.keys())[0]
        assert customer_id.startswith("free_")

    def test_free_signup_duplicate_email_returns_409(self, client, monkeypatch):
        """POST /api/signup/free with an already-registered email must return 409."""
        mock = self._setup_db_mock(monkeypatch)
        client.post("/api/signup/free", json={"email": "free@example.com"})
        resp = client.post("/api/signup/free", json={"email": "free@example.com"})
        assert resp.status_code == 409

    def test_free_signup_case_insensitive_deduplication(self, client, monkeypatch):
        """POST /api/signup/free with mixed-case duplicate email must return 409."""
        self._setup_db_mock(monkeypatch)
        client.post("/api/signup/free", json={"email": "FREE@EXAMPLE.COM"})
        resp = client.post("/api/signup/free", json={"email": "free@example.com"})
        assert resp.status_code == 409

    def test_free_signup_rejects_invalid_email(self, client):
        """POST /api/signup/free with a non-email string must return 422."""
        resp = client.post("/api/signup/free", json={"email": "notanemail"})
        assert resp.status_code == 422


class TestBillingKeyEndpoint:
    """Tests for /api/billing/key second-factor auth (email required)."""

    def _setup_db_mock(self, monkeypatch, pending_keys=None):
        import link_content_scraper.routes as routes_module

        class _MockDb:
            def __init__(self):
                self._keys = pending_keys or {}

            async def claim_pending_key(self, session_id, email):
                entry = self._keys.get(session_id)
                if entry is None or entry["email"] != email:
                    return None
                return self._keys.pop(session_id)["raw_key"]

        mock = _MockDb()
        monkeypatch.setattr(routes_module, "db_client", mock)
        return mock

    def test_get_key_requires_email_param(self, client):
        """GET /api/billing/key without email param must return 422."""
        resp = client.get("/api/billing/key?session_id=cs_test")
        assert resp.status_code == 422

    def test_get_key_requires_session_id_param(self, client):
        """GET /api/billing/key without session_id param must return 422."""
        resp = client.get("/api/billing/key?email=test@example.com")
        assert resp.status_code == 422

    def test_get_key_wrong_email_returns_404(self, client, monkeypatch):
        """GET /api/billing/key with wrong email must return 404."""
        self._setup_db_mock(monkeypatch, {
            "cs_test": {"raw_key": "raw_abc", "email": "real@example.com"}
        })
        resp = client.get("/api/billing/key?session_id=cs_test&email=wrong@example.com")
        assert resp.status_code == 404

    def test_get_key_correct_email_returns_key(self, client, monkeypatch):
        """GET /api/billing/key with correct email returns the raw API key."""
        self._setup_db_mock(monkeypatch, {
            "cs_test": {"raw_key": "raw_abc", "email": "real@example.com"}
        })
        resp = client.get("/api/billing/key?session_id=cs_test&email=real@example.com")
        assert resp.status_code == 200
        assert resp.json()["key"] == "raw_abc"

    def test_get_key_is_one_time(self, client, monkeypatch):
        """GET /api/billing/key is one-time — second call returns 404."""
        self._setup_db_mock(monkeypatch, {
            "cs_test": {"raw_key": "raw_abc", "email": "real@example.com"}
        })
        client.get("/api/billing/key?session_id=cs_test&email=real@example.com")
        resp = client.get("/api/billing/key?session_id=cs_test&email=real@example.com")
        assert resp.status_code == 404


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


class TestScrapeErrorHandling:
    """Cover the HTTPStatusError / generic-error paths in start_scraping."""

    def _setup_auth_mock(self, monkeypatch):
        import link_content_scraper.auth as auth_module

        _customer = Customer(stripe_customer_id="cus_test", email="t@t.com", tier="pro", active=True)

        class _MockDb:
            async def get_customer_by_key(self, key_hash):
                return _customer

            async def get_usage(self, customer_id, month):
                return 0

        monkeypatch.setattr(auth_module, "db_client", _MockDb())

    def _make_status_error(self, code: int):
        import httpx

        request = httpx.Request("GET", "http://example.com/test")
        response = httpx.Response(code, request=request)
        return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)

    def test_403_returns_502_with_blocking_message(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        async def _raise(url, tracker_id, job_id, customer_id):
            raise self._make_status_error(403)

        monkeypatch.setattr(routes_module, "scrape_site", _raise)

        resp = client.post(
            "/api/scrape",
            json={"url": "http://example.com/blocked"},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 502
        assert "blocking" in resp.json()["detail"].lower() or "403" in resp.json()["detail"]

    def test_404_returns_502_with_not_found_message(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        async def _raise(url, tracker_id, job_id, customer_id):
            raise self._make_status_error(404)

        monkeypatch.setattr(routes_module, "scrape_site", _raise)

        resp = client.post(
            "/api/scrape",
            json={"url": "http://example.com/missing"},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 502
        assert "not found" in resp.json()["detail"].lower()

    def test_other_status_returns_502_with_generic_message(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        async def _raise(url, tracker_id, job_id, customer_id):
            raise self._make_status_error(500)

        monkeypatch.setattr(routes_module, "scrape_site", _raise)

        resp = client.post(
            "/api/scrape",
            json={"url": "http://example.com/oops"},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 502
        assert "500" in resp.json()["detail"]

    def test_generic_error_returns_500(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        async def _raise(url, tracker_id, job_id, customer_id):
            raise ValueError("bad data")

        monkeypatch.setattr(routes_module, "scrape_site", _raise)

        resp = client.post(
            "/api/scrape",
            json={"url": "http://example.com/oops"},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 500
        assert "bad data" in resp.json()["detail"]

    def test_progress_tracker_missing_uses_zero_counts(self, client, monkeypatch, tmp_path):
        """If the progress tracker is missing after a successful scrape, response uses zeros."""
        import link_content_scraper.routes as routes_module
        from link_content_scraper.progress import progress_tracker

        self._setup_auth_mock(monkeypatch)

        zip_file = tmp_path / "job.zip"
        zip_file.write_bytes(b"PK\x03\x04")

        async def _scrape(url, tracker_id, job_id, customer_id):
            # Intentionally do NOT init progress_tracker — simulate the bug case.
            await progress_tracker.remove(tracker_id)
            return ([url], str(zip_file))

        monkeypatch.setattr(routes_module, "scrape_site", _scrape)

        resp = client.post(
            "/api/scrape",
            json={"url": "http://example.com/no-tracker"},
            headers={"x-api-key": "test-key"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["successful"] == 0
        assert body["skipped"] == 0
        assert body["failed"] == 0


class TestDownloadSuccess:
    def _setup_auth_mock(self, monkeypatch):
        import link_content_scraper.auth as auth_module

        _customer = Customer(stripe_customer_id="cus_test", email="t@t.com", tier="pro", active=True)

        class _MockDb:
            async def get_customer_by_key(self, key_hash):
                return _customer

            async def get_usage(self, customer_id, month):
                return 0

        monkeypatch.setattr(auth_module, "db_client", _MockDb())

    def test_download_returns_file_and_schedules_cleanup(self, client, monkeypatch, tmp_path):
        """A valid job_id owned by the caller returns the ZIP file and the cleanup task is created."""
        import time
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        zip_file = tmp_path / "owned.zip"
        zip_file.write_bytes(b"PK\x03\x04valid-zip-bytes")
        routes_module._results["job_owned"] = {
            "zip_path": str(zip_file),
            "customer_id": "cus_test",
        }
        # Short, non-zero delay so the FileResponse can finish streaming before cleanup runs.
        monkeypatch.setattr(routes_module, "CLEANUP_DELAY_SECONDS", 0.2)

        try:
            # Using TestClient as a context manager keeps the lifespan loop alive long
            # enough for the background cleanup task to complete.
            with client:
                resp = client.get("/api/download/job_owned", headers={"x-api-key": "test-key"})
                assert resp.status_code == 200
                assert resp.content.startswith(b"PK")
                assert "scraped-content-job_owned.zip" in resp.headers.get("content-disposition", "")

                deadline = time.time() + 3
                while time.time() < deadline and (
                    zip_file.exists() or "job_owned" in routes_module._results
                ):
                    time.sleep(0.05)

            assert not zip_file.exists()
            assert "job_owned" not in routes_module._results
        finally:
            routes_module._results.pop("job_owned", None)

    def test_download_cleanup_handles_missing_file(self, client, monkeypatch, tmp_path, caplog):
        """Cleanup must not raise even if the zip file is already gone."""
        import logging
        import time
        import link_content_scraper.routes as routes_module

        self._setup_auth_mock(monkeypatch)

        zip_file = tmp_path / "vanish.zip"
        zip_file.write_bytes(b"PK\x03\x04")
        routes_module._results["job_vanish"] = {
            "zip_path": str(zip_file),
            "customer_id": "cus_test",
        }
        monkeypatch.setattr(routes_module, "CLEANUP_DELAY_SECONDS", 0.2)

        # Force unlink to raise OSError to exercise the `except OSError` branch
        original_unlink = routes_module.Path.unlink

        def _raising_unlink(self, missing_ok=False):
            if str(self) == str(zip_file):
                raise OSError("simulated unlink failure")
            return original_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(routes_module.Path, "unlink", _raising_unlink)

        try:
            with client:
                with caplog.at_level(logging.WARNING, logger="link_content_scraper.routes"):
                    resp = client.get("/api/download/job_vanish", headers={"x-api-key": "test-key"})
                assert resp.status_code == 200

                deadline = time.time() + 3
                while time.time() < deadline and "job_vanish" in routes_module._results:
                    time.sleep(0.05)

            assert "job_vanish" not in routes_module._results
            assert any("Failed to clean up" in m for m in caplog.messages)
        finally:
            routes_module._results.pop("job_vanish", None)


class TestBillingPages:
    def test_billing_page_returns_html(self, client):
        resp = client.get("/billing")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_billing_success_page_returns_html(self, client):
        resp = client.get("/billing/success")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestCheckoutEndpoint:
    def test_checkout_returns_url(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        async def _create_session(tier, email):
            return f"https://checkout.test/{tier}/{email}"

        monkeypatch.setattr(routes_module, "create_checkout_session", _create_session)

        resp = client.post(
            "/api/billing/checkout",
            json={"tier": "starter", "email": "buyer@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"url": "https://checkout.test/starter/buyer@example.com"}


class TestPortalEndpoint:
    def test_portal_requires_auth(self, client):
        resp = client.get("/billing/portal")
        assert resp.status_code == 401

    def test_portal_returns_url_when_authed(self, client, monkeypatch):
        import link_content_scraper.auth as auth_module
        import link_content_scraper.routes as routes_module

        _customer = Customer(stripe_customer_id="cus_test", email="t@t.com", tier="pro", active=True)

        class _MockDb:
            async def get_customer_by_key(self, key_hash):
                return _customer

            async def get_usage(self, customer_id, month):
                return 0

        monkeypatch.setattr(auth_module, "db_client", _MockDb())

        async def _portal(stripe_customer_id):
            return f"https://billing.test/{stripe_customer_id}"

        monkeypatch.setattr(routes_module, "create_portal_session", _portal)

        resp = client.get("/billing/portal", headers={"x-api-key": "test-key"})
        assert resp.status_code == 200
        assert resp.json() == {"url": "https://billing.test/cus_test"}


class TestStripeWebhookEndpoint:
    def test_webhook_returns_400_on_invalid_signature(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        async def _raise(payload, sig_header):
            raise ValueError("bad signature")

        monkeypatch.setattr(routes_module, "handle_webhook", _raise)

        resp = client.post(
            "/api/webhooks/stripe",
            content=b"raw-payload",
            headers={"stripe-signature": "bad"},
        )
        assert resp.status_code == 400
        assert "bad signature" in resp.json()["detail"]

    def test_webhook_returns_200_on_success(self, client, monkeypatch):
        import link_content_scraper.routes as routes_module

        async def _ok(payload, sig_header):
            return None

        monkeypatch.setattr(routes_module, "handle_webhook", _ok)

        resp = client.post(
            "/api/webhooks/stripe",
            content=b"raw-payload",
            headers={"stripe-signature": "sig_test"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestFreeSignupRollback:
    def _install_db(self, monkeypatch, db):
        import link_content_scraper.auth as auth_module
        import link_content_scraper.routes as routes_module
        monkeypatch.setattr(auth_module, "db_client", db)
        monkeypatch.setattr(routes_module, "db_client", db)

    def test_create_api_key_failure_triggers_rollback_and_returns_500(self, client, monkeypatch, caplog):
        import logging

        class _MockDb:
            def __init__(self):
                self.customers = {}
                self.deleted = []

            async def get_customer_by_email(self, email):
                return None

            async def create_customer(self, customer_id, email, tier):
                self.customers[customer_id] = {"email": email, "tier": tier}

            async def create_api_key(self, key_hash, customer_id):
                raise RuntimeError("api key insert failed")

            async def store_pending_key(self, *args, **kwargs):
                pass

            async def delete_customer(self, customer_id):
                self.deleted.append(customer_id)
                self.customers.pop(customer_id, None)

        db = _MockDb()
        self._install_db(monkeypatch, db)

        with caplog.at_level(logging.ERROR, logger="link_content_scraper.routes"):
            resp = client.post("/api/signup/free", json={"email": "rollback@example.com"})

        assert resp.status_code == 500
        assert "Account creation failed" in resp.json()["detail"]
        assert len(db.deleted) == 1, "delete_customer must run as rollback"

    def test_rollback_failure_is_logged_and_still_returns_500(self, client, monkeypatch, caplog):
        import logging

        class _MockDb:
            def __init__(self):
                self.customers = {}

            async def get_customer_by_email(self, email):
                return None

            async def create_customer(self, customer_id, email, tier):
                self.customers[customer_id] = {"email": email, "tier": tier}

            async def create_api_key(self, key_hash, customer_id):
                raise RuntimeError("api key insert failed")

            async def store_pending_key(self, *args, **kwargs):
                pass

            async def delete_customer(self, customer_id):
                raise RuntimeError("delete failed too")

        db = _MockDb()
        self._install_db(monkeypatch, db)

        with caplog.at_level(logging.ERROR, logger="link_content_scraper.routes"):
            resp = client.post("/api/signup/free", json={"email": "rollback2@example.com"})

        assert resp.status_code == 500
        assert any("manual cleanup" in m for m in caplog.messages)


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
