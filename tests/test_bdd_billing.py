# ABOUTME: BDD step definitions for billing and subscription lifecycle scenarios.
# ABOUTME: Exercises checkout, quota enforcement, and payment webhook state transitions.

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_bdd import given, scenarios, then, when

import link_content_scraper.auth as auth_module
import link_content_scraper.billing as billing_module
from link_content_scraper.auth import Customer

scenarios("features/billing.feature")


# ── Stateful in-memory database ───────────────────────────────────────────────

class _StateDb:
    """In-memory substitute for DatabaseClient that tracks full billing state."""

    def __init__(self):
        self.customers: dict[str, dict] = {}   # customer_id -> {email, tier, active}
        self.api_keys: dict[str, dict] = {}    # key_hash -> {customer_id, active}
        self.usage: dict[tuple, int] = {}      # (customer_id, month) -> count

    def add_customer(self, customer_id: str, email: str, tier: str, *, active: bool = True):
        self.customers[customer_id] = {"email": email, "tier": tier, "active": active}

    def add_api_key(self, raw_key: str, customer_id: str, *, active: bool = True):
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        self.api_keys[key_hash] = {"customer_id": customer_id, "active": active}

    def set_usage(self, customer_id: str, month: str, count: int):
        self.usage[(customer_id, month)] = count

    # ── DatabaseClient interface ───────────────────────────────────────────────

    async def get_customer_by_key(self, key_hash: str) -> Customer | None:
        rec = self.api_keys.get(key_hash)
        if rec is None:
            return None
        cust = self.customers.get(rec["customer_id"])
        if cust is None:
            return None
        return Customer(
            stripe_customer_id=rec["customer_id"],
            email=cust["email"],
            tier=cust["tier"],
            active=rec["active"] and cust["active"],
        )

    async def get_usage(self, customer_id: str, month: str) -> int:
        return self.usage.get((customer_id, month), 0)

    async def increment_usage(self, customer_id: str, month: str) -> None:
        key = (customer_id, month)
        self.usage[key] = self.usage.get(key, 0) + 1

    async def create_customer(self, customer_id: str, email: str, tier: str) -> None:
        self.customers[customer_id] = {"email": email, "tier": tier, "active": True}

    async def create_api_key(self, key_hash: str, customer_id: str) -> None:
        self.api_keys[key_hash] = {"customer_id": customer_id, "active": True}

    async def update_customer_tier(self, customer_id: str, tier: str) -> None:
        if customer_id in self.customers:
            self.customers[customer_id]["tier"] = tier

    async def deactivate_customer_keys(self, customer_id: str) -> None:
        for rec in self.api_keys.values():
            if rec["customer_id"] == customer_id:
                rec["active"] = False

    async def set_customer_active(self, customer_id: str, active: bool) -> None:
        if customer_id in self.customers:
            self.customers[customer_id]["active"] = active

    async def reactivate_customer_keys(self, customer_id: str) -> None:
        for rec in self.api_keys.values():
            if rec["customer_id"] == customer_id:
                rec["active"] = True


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def ctx():
    """Mutable context dict shared across steps within a single scenario."""
    return {}


@pytest.fixture()
def db(monkeypatch):
    """Stateful in-memory DB patched into both auth and billing modules."""
    state = _StateDb()
    monkeypatch.setattr(auth_module, "db_client", state)
    monkeypatch.setattr(billing_module, "db_client", state)
    return state


@pytest.fixture(autouse=True)
def _patch_stripe_webhook(monkeypatch):
    """Make stripe.Webhook.construct_event return the parsed payload directly."""
    def _construct(payload, sig_header, secret):
        return json.loads(payload)
    monkeypatch.setattr(billing_module.stripe.Webhook, "construct_event", _construct)


@pytest.fixture(autouse=True)
def _patch_scrape_site(monkeypatch, tmp_path):
    """Stub scrape_site so billing BDD tests never make real HTTP calls."""
    import link_content_scraper.routes as routes_module
    from link_content_scraper.progress import progress_tracker

    fake_zip = tmp_path / "fake.zip"
    fake_zip.write_bytes(b"PK")  # minimal zip magic bytes

    async def _fake_scrape(url, tracker_id, job_id, customer_id=None):
        await progress_tracker.init(tracker_id, total=1)
        await progress_tracker.increment(tracker_id, processed=1, potential_successful=1)
        return [url], str(fake_zip)

    monkeypatch.setattr(routes_module, "scrape_site", _fake_scrape)


# ── Helpers ───────────────────────────────────────────────────────────────────

_CUSTOMER_ID = "cus_bdd_billing"
_EMAIL = "subscriber@example.com"
_API_KEY = "pf_test_bdd_billing_key_abc123"
_SESSION_ID = "cs_test_bdd_session_xyz"
_CURRENT_MONTH = datetime.now(UTC).strftime("%Y-%m")

_TIER_LIMITS = {"starter": 5_000, "pro": 25_000}


def _webhook_payload(event_type: str, obj: dict) -> bytes:
    event = {"type": event_type, "data": {"object": obj}}
    return json.dumps(event).encode()


def _scrape(client, api_key: str):
    return client.post(
        "/api/scrape",
        json={"url": "https://example.com"},
        headers={"x-api-key": api_key},
    )


def _post_webhook(client, event_type: str, obj: dict):
    return client.post(
        "/api/webhooks/stripe",
        content=_webhook_payload(event_type, obj),
        headers={"stripe-signature": "ignored", "content-type": "application/json"},
    )


def _checkout_obj(session_id: str, customer_id: str, email: str, tier: str) -> dict:
    return {
        "id": session_id,
        "customer": customer_id,
        "customer_email": email,
        "metadata": {"tier": tier},
    }


def _subscription_obj(customer_id: str, tier: str) -> dict:
    return {"customer": customer_id, "metadata": {"tier": tier}}


def _invoice_obj(customer_id: str) -> dict:
    return {"customer": customer_id}


# ── Given steps ───────────────────────────────────────────────────────────────

@given("a checkout.session.completed webhook fires for a new starter subscriber", target_fixture="ctx")
def given_checkout_webhook(ctx, db):
    ctx["db"] = db
    ctx["session_id"] = _SESSION_ID
    ctx["customer_id"] = _CUSTOMER_ID
    return ctx


@given("an active starter subscriber with a valid API key", target_fixture="ctx")
def given_active_subscriber(ctx, db):
    db.add_customer(_CUSTOMER_ID, _EMAIL, "starter")
    db.add_api_key(_API_KEY, _CUSTOMER_ID)
    ctx["db"] = db
    ctx["api_key"] = _API_KEY
    ctx["customer_id"] = _CUSTOMER_ID
    return ctx


@given("the subscriber has consumed their entire monthly quota")
def given_quota_exhausted(ctx):
    db = ctx["db"]
    limit = _TIER_LIMITS[db.customers[_CUSTOMER_ID]["tier"]]
    db.set_usage(_CUSTOMER_ID, _CURRENT_MONTH, limit)


@given("an invoice.payment_failed webhook has deactivated their key")
def given_payment_failed(ctx, client):
    resp = _post_webhook(client, "invoice.payment_failed", _invoice_obj(_CUSTOMER_ID))
    assert resp.status_code == 200


# ── When steps ────────────────────────────────────────────────────────────────

@when("the webhook is delivered to the API")
def when_webhook_delivered(ctx, client):
    obj = _checkout_obj(ctx["session_id"], ctx["customer_id"], _EMAIL, "starter")
    resp = _post_webhook(client, "checkout.session.completed", obj)
    ctx["webhook_response"] = resp


@when("they submit a scrape request with their API key")
def when_scrape_submitted(ctx, client):
    ctx["scrape_response"] = _scrape(client, ctx["api_key"])


@when("an invoice.payment_failed webhook fires for that subscriber")
def when_payment_failed(ctx, client):
    resp = _post_webhook(client, "invoice.payment_failed", _invoice_obj(_CUSTOMER_ID))
    assert resp.status_code == 200


@when("an invoice.payment_succeeded webhook fires for that subscriber")
def when_payment_succeeded(ctx, client):
    resp = _post_webhook(client, "invoice.payment_succeeded", _invoice_obj(_CUSTOMER_ID))
    assert resp.status_code == 200


@when("a customer.subscription.deleted webhook fires for that subscriber")
def when_subscription_deleted(ctx, client):
    resp = _post_webhook(client, "customer.subscription.deleted", _invoice_obj(_CUSTOMER_ID))
    assert resp.status_code == 200


@when("a customer.subscription.updated webhook fires upgrading them to pro")
def when_subscription_upgraded(ctx, client):
    resp = _post_webhook(client, "customer.subscription.updated", _subscription_obj(_CUSTOMER_ID, "pro"))
    assert resp.status_code == 200


# ── Then steps ────────────────────────────────────────────────────────────────

@then("the customer record exists in the database")
def then_customer_exists(ctx):
    assert ctx["webhook_response"].status_code == 200
    db = ctx["db"]
    assert _CUSTOMER_ID in db.customers
    assert db.customers[_CUSTOMER_ID]["tier"] == "starter"


@then("the API key can be claimed once by session ID")
def then_key_claimable_once(ctx, client):
    resp = client.get(f"/api/billing/key?session_id={ctx['session_id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert "key" in data
    assert len(data["key"]) > 10
    ctx["claimed_key"] = data["key"]


@then("claiming the API key a second time returns 404")
def then_key_not_claimable_twice(ctx, client):
    resp = client.get(f"/api/billing/key?session_id={ctx['session_id']}")
    assert resp.status_code == 404


@then("the scrape request succeeds with status 200")
def then_scrape_succeeds(ctx):
    assert ctx["scrape_response"].status_code == 200


@then("the response is 429 Too Many Requests")
def then_response_is_429(ctx):
    assert ctx["scrape_response"].status_code == 429


@then("the response body contains error, detail, and resetsAt fields")
def then_quota_response_body(ctx):
    data = ctx["scrape_response"].json()
    detail = data.get("detail", {})
    assert detail.get("error") == "quota_exceeded"
    assert "detail" in detail
    assert "resetsAt" in detail


@then("subsequent scrape requests with their API key return 401")
def then_scrape_returns_401(ctx, client):
    resp = _scrape(client, ctx["api_key"])
    assert resp.status_code == 401


@then("subsequent scrape requests with their API key return 200")
def then_scrape_returns_200(ctx, client):
    resp = _scrape(client, ctx["api_key"])
    assert resp.status_code == 200
