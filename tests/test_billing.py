# ABOUTME: Unit tests for Stripe billing — checkout, portal, and webhook handling.
# ABOUTME: Mocks Stripe SDK and DatabaseClient to test billing logic in isolation.

import json
import pytest
import stripe
from unittest.mock import AsyncMock, MagicMock, patch

import link_content_scraper.auth as auth_module
import link_content_scraper.billing as billing_module
from link_content_scraper.billing import (
    _generate_api_key,
    create_checkout_session,
    create_portal_session,
    handle_webhook,
)


# -- Helpers -------------------------------------------------------------------

class MockDatabaseClient:
    def __init__(self):
        self.customers: dict = {}
        self.api_keys: dict = {}
        self.tiers: dict = {}
        self.deactivated: list = []
        self.active_state: dict = {}

    async def create_customer(self, stripe_customer_id, email, tier):
        self.customers[stripe_customer_id] = {"email": email, "tier": tier}

    async def create_api_key(self, key_hash, customer_id):
        self.api_keys[key_hash] = customer_id

    async def update_customer_tier(self, stripe_customer_id, tier):
        self.tiers[stripe_customer_id] = tier

    async def deactivate_customer_keys(self, stripe_customer_id):
        self.deactivated.append(stripe_customer_id)

    async def set_customer_active(self, stripe_customer_id, active):
        self.active_state[stripe_customer_id] = active


@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    db = MockDatabaseClient()
    monkeypatch.setattr(auth_module, "db_client", db)
    monkeypatch.setattr(billing_module, "db_client", db)
    return db


# -- _generate_api_key ---------------------------------------------------------

class TestGenerateApiKey:
    def test_returns_raw_and_hash(self):
        raw, hashed = _generate_api_key()
        assert isinstance(raw, str) and len(raw) > 20
        assert isinstance(hashed, str) and len(hashed) == 64  # sha256 hex

    def test_raw_and_hash_differ(self):
        raw, hashed = _generate_api_key()
        assert raw != hashed

    def test_each_call_produces_unique_key(self):
        raw1, _ = _generate_api_key()
        raw2, _ = _generate_api_key()
        assert raw1 != raw2


# -- create_checkout_session ---------------------------------------------------

class TestCreateCheckoutSession:
    @pytest.mark.asyncio
    async def test_returns_redirect_url(self):
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/test"

        with patch("stripe.checkout.Session.create", return_value=mock_session):
            url = await create_checkout_session("starter", "user@example.com")

        assert url == "https://checkout.stripe.com/pay/test"

    @pytest.mark.asyncio
    async def test_uses_correct_price_id(self, monkeypatch):
        monkeypatch.setattr(billing_module, "STRIPE_PRICE_IDS", {"pro": "price_pro_test"})
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/test"

        with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
            await create_checkout_session("pro", "user@example.com")

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["line_items"][0]["price"] == "price_pro_test"

    @pytest.mark.asyncio
    async def test_invalid_tier_raises(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            await create_checkout_session("platinum", "user@example.com")


# -- create_portal_session -----------------------------------------------------

class TestCreatePortalSession:
    @pytest.mark.asyncio
    async def test_returns_portal_url(self):
        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/session/test"

        with patch("stripe.billing_portal.Session.create", return_value=mock_session):
            url = await create_portal_session("cus_123")

        assert url == "https://billing.stripe.com/session/test"


# -- handle_webhook ------------------------------------------------------------

def _make_event(event_type: str, data: dict) -> dict:
    return {"type": event_type, "data": {"object": data}}


class TestHandleWebhook:
    @pytest.mark.asyncio
    async def test_rejects_invalid_signature(self):
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.error.SignatureVerificationError("bad sig", sig_header="bad-sig"),
        ):
            with pytest.raises(ValueError, match="Invalid webhook"):
                await handle_webhook(b"payload", "bad-sig")

    @pytest.mark.asyncio
    async def test_checkout_completed_missing_customer_raises(self, mock_db):
        event = _make_event("checkout.session.completed", {
            "customer_email": "new@example.com",
            "metadata": {"tier": "starter"},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            with pytest.raises(ValueError, match="Missing customer ID"):
                await handle_webhook(b"payload", "sig")

        assert len(mock_db.customers) == 0

    @pytest.mark.asyncio
    async def test_checkout_completed_creates_customer_and_key(self, mock_db):
        event = _make_event("checkout.session.completed", {
            "customer": "cus_abc",
            "customer_email": "new@example.com",
            "metadata": {"tier": "starter"},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert "cus_abc" in mock_db.customers
        assert mock_db.customers["cus_abc"]["tier"] == "starter"
        assert len(mock_db.api_keys) == 1

    @pytest.mark.asyncio
    async def test_subscription_updated_changes_tier(self, mock_db):
        event = _make_event("customer.subscription.updated", {
            "customer": "cus_abc",
            "metadata": {"tier": "pro"},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert mock_db.tiers["cus_abc"] == "pro"

    @pytest.mark.asyncio
    async def test_subscription_updated_missing_tier_does_not_update(self, mock_db):
        event = _make_event("customer.subscription.updated", {
            "customer": "cus_abc",
            "metadata": {},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert "cus_abc" not in mock_db.tiers

    @pytest.mark.asyncio
    async def test_subscription_deleted_sets_free_and_deactivates(self, mock_db):
        event = _make_event("customer.subscription.deleted", {
            "customer": "cus_abc",
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert mock_db.tiers["cus_abc"] == "free"
        assert "cus_abc" in mock_db.deactivated

    @pytest.mark.asyncio
    async def test_payment_failed_deactivates_keys(self, mock_db):
        event = _make_event("invoice.payment_failed", {
            "customer": "cus_abc",
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert "cus_abc" in mock_db.deactivated

    @pytest.mark.asyncio
    async def test_unknown_event_is_ignored(self, mock_db):
        event = _make_event("some.unknown.event", {"customer": "cus_abc"})
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert len(mock_db.customers) == 0
