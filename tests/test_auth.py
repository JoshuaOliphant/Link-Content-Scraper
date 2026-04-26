# ABOUTME: Unit tests for API key authentication and usage enforcement middleware.
# ABOUTME: Uses a mock DatabaseClient to test auth logic without Supabase calls.

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import link_content_scraper.auth as auth_module
from link_content_scraper.auth import Customer, require_api_key


# -- Mock DB client ------------------------------------------------------------

class MockDatabaseClient:
    def __init__(self, customer: Customer | None = None, usage: int = 0):
        self._customer = customer
        self._usage = usage
        self.increment_calls: list[tuple[str, str]] = []

    async def get_customer_by_key(self, key_hash: str) -> Customer | None:
        return self._customer

    async def get_usage(self, customer_id: str, month: str) -> int:
        return self._usage

    async def increment_usage(self, customer_id: str, month: str) -> None:
        self.increment_calls.append((customer_id, month))


def _make_client(mock_db: MockDatabaseClient) -> TestClient:
    """Build a minimal FastAPI test app wired with the auth dependency."""
    auth_module.db_client = mock_db

    app = FastAPI()

    @app.post("/test")
    async def _route(customer: Customer = Depends(require_api_key)):
        return {"customer_id": customer.stripe_customer_id, "tier": customer.tier}

    return TestClient(app, raise_server_exceptions=True)


VALID_KEY = "test-api-key-12345"
ACTIVE_CUSTOMER = Customer(
    stripe_customer_id="cus_test",
    email="test@example.com",
    tier="starter",
    active=True,
)


# -- Tests ---------------------------------------------------------------------

class TestRequireApiKey:
    def test_valid_key_returns_customer(self, monkeypatch):
        mock_db = MockDatabaseClient(customer=ACTIVE_CUSTOMER, usage=0)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 200
        assert resp.json()["customer_id"] == "cus_test"

    def test_missing_key_returns_401(self, monkeypatch):
        mock_db = MockDatabaseClient(customer=ACTIVE_CUSTOMER)
        client = _make_client(mock_db)

        resp = client.post("/test")

        assert resp.status_code == 401

    def test_unknown_key_returns_401(self, monkeypatch):
        mock_db = MockDatabaseClient(customer=None)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": "bad-key"})

        assert resp.status_code == 401

    def test_inactive_customer_returns_401(self, monkeypatch):
        inactive = Customer(
            stripe_customer_id="cus_test",
            email="test@example.com",
            tier="starter",
            active=False,
        )
        mock_db = MockDatabaseClient(customer=inactive)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 401

    def test_over_limit_returns_429(self, monkeypatch):
        # starter limit is 5000
        mock_db = MockDatabaseClient(customer=ACTIVE_CUSTOMER, usage=5_000)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 429

    def test_at_limit_minus_one_passes(self, monkeypatch):
        mock_db = MockDatabaseClient(customer=ACTIVE_CUSTOMER, usage=4_999)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 200

    def test_free_tier_limit_is_100(self, monkeypatch):
        free_customer = Customer(
            stripe_customer_id="cus_free",
            email="free@example.com",
            tier="free",
            active=True,
        )
        mock_db = MockDatabaseClient(customer=free_customer, usage=100)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 429

    def test_business_tier_limit_is_150000(self, monkeypatch):
        biz_customer = Customer(
            stripe_customer_id="cus_biz",
            email="biz@example.com",
            tier="business",
            active=True,
        )
        mock_db = MockDatabaseClient(customer=biz_customer, usage=149_999)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 200

    def test_quota_exceeded_returns_429_with_resets_at(self):
        mock_db = MockDatabaseClient(customer=ACTIVE_CUSTOMER, usage=5_000)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 429
        body = resp.json()["detail"]
        assert body["error"] == "quota_exceeded"
        assert "detail" in body
        assert "resetsAt" in body

    def test_resets_at_is_first_of_next_month(self):
        from datetime import UTC, datetime

        mock_db = MockDatabaseClient(customer=ACTIVE_CUSTOMER, usage=5_000)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 429
        resets_at_str = resp.json()["detail"]["resetsAt"]
        resets_at = datetime.fromisoformat(resets_at_str)

        assert resets_at.day == 1
        assert resets_at.hour == 0
        assert resets_at.minute == 0
        assert resets_at.second == 0

        now = datetime.now(UTC)
        if now.month == 12:
            assert resets_at.year == now.year + 1
            assert resets_at.month == 1
        else:
            assert resets_at.year == now.year
            assert resets_at.month == now.month + 1

    def test_unknown_tier_returns_500(self):
        weird_customer = Customer(
            stripe_customer_id="cus_weird",
            email="weird@example.com",
            tier="platinum",
            active=True,
        )
        mock_db = MockDatabaseClient(customer=weird_customer)
        client = _make_client(mock_db)

        resp = client.post("/test", headers={"x-api-key": VALID_KEY})

        assert resp.status_code == 500
        assert "configuration" in resp.json()["detail"].lower()


# -- DatabaseClient unit tests -------------------------------------------------

class _Result:
    def __init__(self, data):
        self.data = data


class _Chain:
    """Chainable fake supabase query builder. Returns ``self`` for everything
    except ``execute()``, which returns an awaitable resolving to ``response``.
    Calls are recorded so tests can verify the chain.
    """

    def __init__(self, response):
        self._response = response
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        if name == "execute":
            async def _exec():
                return self._response
            return _exec

        def _method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return _method


class _SupabaseMock:
    def __init__(self):
        self.table_chains: dict[str, _Chain] = {}
        self.rpc_chains: dict[str, _Chain] = {}
        self.last_table: str | None = None
        self.last_rpc: tuple[str, dict] | None = None

    def set_table_response(self, name: str, response):
        self.table_chains[name] = _Chain(response)

    def set_rpc_response(self, name: str, response):
        self.rpc_chains[name] = _Chain(response)

    def table(self, name: str):
        self.last_table = name
        if name not in self.table_chains:
            self.table_chains[name] = _Chain(_Result(None))
        return self.table_chains[name]

    def rpc(self, name: str, params: dict):
        self.last_rpc = (name, params)
        if name not in self.rpc_chains:
            self.rpc_chains[name] = _Chain(_Result(None))
        return self.rpc_chains[name]


@pytest.fixture()
def db_with_mock():
    from link_content_scraper.auth import DatabaseClient

    db = DatabaseClient()
    supabase = _SupabaseMock()
    db._supabase = supabase
    return db, supabase


class TestDatabaseClientCustomerByKey:
    async def test_returns_customer_when_key_active_and_customer_active(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", _Result({
            "active": True,
            "customers": {
                "stripe_customer_id": "cus_x",
                "email": "x@example.com",
                "tier": "pro",
                "active": True,
            },
        }))
        result = await db.get_customer_by_key("hash_value")
        assert result is not None
        assert result.stripe_customer_id == "cus_x"
        assert result.tier == "pro"
        assert result.active is True

    async def test_inactive_when_key_inactive(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", _Result({
            "active": False,
            "customers": {
                "stripe_customer_id": "cus_x",
                "email": "x@example.com",
                "tier": "pro",
                "active": True,
            },
        }))
        result = await db.get_customer_by_key("hash_value")
        assert result.active is False

    async def test_returns_none_when_no_result(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", _Result(None))
        result = await db.get_customer_by_key("hash_value")
        assert result is None

    async def test_returns_none_when_result_is_none_object(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", None)
        result = await db.get_customer_by_key("hash_value")
        assert result is None

    async def test_returns_none_when_customer_orphaned(self, db_with_mock, caplog):
        import logging

        db, sb = db_with_mock
        sb.set_table_response("api_keys", _Result({
            "active": True,
            "customers": None,
        }))
        with caplog.at_level(logging.ERROR, logger="link_content_scraper.auth"):
            result = await db.get_customer_by_key("hash_value")
        assert result is None
        assert any("orphaned" in m for m in caplog.messages)


class TestDatabaseClientUsage:
    async def test_get_usage_returns_count(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("usage", _Result({"url_count": 42}))
        assert await db.get_usage("cus_x", "2026-04") == 42

    async def test_get_usage_returns_zero_when_missing(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("usage", _Result(None))
        assert await db.get_usage("cus_x", "2026-04") == 0

    async def test_get_usage_returns_zero_when_result_is_none(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("usage", None)
        assert await db.get_usage("cus_x", "2026-04") == 0

    async def test_increment_usage_calls_rpc(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_rpc_response("increment_usage", _Result(None))
        await db.increment_usage("cus_x", "2026-04")
        assert sb.last_rpc == (
            "increment_usage",
            {"p_customer_id": "cus_x", "p_month": "2026-04"},
        )


class TestDatabaseClientCustomerCRUD:
    async def test_create_customer(self, db_with_mock):
        db, sb = db_with_mock
        await db.create_customer("cus_new", "new@example.com", "starter")
        assert sb.last_table == "customers"
        chain = sb.table_chains["customers"]
        # First call after table() is insert(...)
        assert chain.calls[0][0] == "insert"
        assert chain.calls[0][1][0] == {
            "stripe_customer_id": "cus_new",
            "email": "new@example.com",
            "tier": "starter",
        }

    async def test_create_api_key(self, db_with_mock):
        db, sb = db_with_mock
        await db.create_api_key("hash123", "cus_x")
        assert sb.last_table == "api_keys"
        chain = sb.table_chains["api_keys"]
        assert chain.calls[0][0] == "insert"

    async def test_update_customer_tier(self, db_with_mock):
        db, sb = db_with_mock
        await db.update_customer_tier("cus_x", "pro")
        chain = sb.table_chains["customers"]
        assert ("update", ({"tier": "pro"},), {}) in chain.calls

    async def test_deactivate_customer_keys(self, db_with_mock):
        db, sb = db_with_mock
        await db.deactivate_customer_keys("cus_x")
        chain = sb.table_chains["api_keys"]
        assert ("update", ({"active": False},), {}) in chain.calls

    async def test_set_customer_active_true(self, db_with_mock):
        db, sb = db_with_mock
        await db.set_customer_active("cus_x", True)
        chain = sb.table_chains["customers"]
        assert ("update", ({"active": True},), {}) in chain.calls

    async def test_reactivate_customer_keys(self, db_with_mock):
        db, sb = db_with_mock
        await db.reactivate_customer_keys("cus_x")
        chain = sb.table_chains["api_keys"]
        assert ("update", ({"active": True},), {}) in chain.calls

    async def test_delete_customer(self, db_with_mock):
        db, sb = db_with_mock
        await db.delete_customer("cus_x")
        chain = sb.table_chains["customers"]
        names = [c[0] for c in chain.calls]
        assert "delete" in names


class TestDatabaseClientLookups:
    async def test_get_customer_by_email_found(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("customers", _Result({
            "stripe_customer_id": "cus_y",
            "email": "y@example.com",
            "tier": "free",
            "active": True,
        }))
        result = await db.get_customer_by_email("y@example.com")
        assert result.stripe_customer_id == "cus_y"
        assert result.email == "y@example.com"

    async def test_get_customer_by_email_not_found(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("customers", _Result(None))
        assert await db.get_customer_by_email("missing@example.com") is None

    async def test_get_customer_by_email_none_result(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("customers", None)
        assert await db.get_customer_by_email("missing@example.com") is None

    async def test_get_customer_by_id_found(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("customers", _Result({
            "stripe_customer_id": "cus_z",
            "email": "z@example.com",
            "tier": "pro",
            "active": False,
        }))
        result = await db.get_customer_by_id("cus_z")
        assert result.tier == "pro"
        assert result.active is False

    async def test_get_customer_by_id_not_found(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("customers", _Result(None))
        assert await db.get_customer_by_id("cus_missing") is None

    async def test_get_customer_by_id_none_result(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("customers", None)
        assert await db.get_customer_by_id("cus_missing") is None

    async def test_has_api_key_for_customer_true(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", _Result([{"key_hash": "h"}]))
        assert await db.has_api_key_for_customer("cus_x") is True

    async def test_has_api_key_for_customer_false_empty(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", _Result([]))
        assert await db.has_api_key_for_customer("cus_x") is False

    async def test_has_api_key_for_customer_false_none(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("api_keys", None)
        assert await db.has_api_key_for_customer("cus_x") is False


class TestDatabaseClientPendingKeys:
    async def test_store_pending_key(self, db_with_mock):
        db, sb = db_with_mock
        await db.store_pending_key("sess_1", "raw_key", "buyer@example.com", ttl_hours=1)
        chain = sb.table_chains["pending_keys"]
        upserts = [c for c in chain.calls if c[0] == "upsert"]
        assert upserts, "Expected upsert call"
        payload = upserts[0][1][0]
        assert payload["session_id"] == "sess_1"
        assert payload["raw_key"] == "raw_key"
        assert payload["email"] == "buyer@example.com"
        assert "expires_at" in payload

    async def test_claim_pending_key_success(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("pending_keys", _Result({
            "raw_key": "the_key",
            "email": "buyer@example.com",
        }))
        result = await db.claim_pending_key("sess_1", "buyer@example.com")
        assert result == "the_key"

    async def test_claim_pending_key_not_found(self, db_with_mock, caplog):
        import logging

        db, sb = db_with_mock
        sb.set_table_response("pending_keys", _Result(None))
        with caplog.at_level(logging.WARNING, logger="link_content_scraper.auth"):
            result = await db.claim_pending_key("sess_missing", "buyer@example.com")
        assert result is None
        assert any("not found" in m.lower() or "expired" in m.lower() for m in caplog.messages)

    async def test_claim_pending_key_none_result(self, db_with_mock):
        db, sb = db_with_mock
        sb.set_table_response("pending_keys", None)
        assert await db.claim_pending_key("sess_missing", "buyer@example.com") is None

    async def test_claim_pending_key_email_mismatch(self, db_with_mock, caplog):
        import logging

        db, sb = db_with_mock
        sb.set_table_response("pending_keys", _Result({
            "raw_key": "the_key",
            "email": "real@example.com",
        }))
        with caplog.at_level(logging.WARNING, logger="link_content_scraper.auth"):
            result = await db.claim_pending_key("sess_1", "wrong@example.com")
        assert result is None
        assert any("email mismatch" in m.lower() for m in caplog.messages)


class TestDatabaseClientLazyInit:
    async def test_get_supabase_caches_client(self, monkeypatch):
        from link_content_scraper import auth as auth_module

        created = []

        async def fake_acreate_client(url, key):
            created.append((url, key))
            return _SupabaseMock()

        monkeypatch.setattr("supabase.acreate_client", fake_acreate_client)
        monkeypatch.setattr(auth_module, "SUPABASE_URL", "https://fake.supabase.co")
        monkeypatch.setattr(auth_module, "SUPABASE_KEY", "fake_key")

        db = auth_module.DatabaseClient()
        c1 = await db._get_supabase()
        c2 = await db._get_supabase()
        assert c1 is c2
        assert len(created) == 1
