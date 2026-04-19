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
