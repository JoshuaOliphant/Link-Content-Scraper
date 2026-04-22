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
        self.reactivated: list = []
        self.active_state: dict = {}
        self.pending_keys: dict = {}  # session_id -> {raw_key, email}

    async def create_customer(self, stripe_customer_id, email, tier):
        self.customers[stripe_customer_id] = {"email": email, "tier": tier}

    async def create_api_key(self, key_hash, customer_id):
        self.api_keys[key_hash] = customer_id

    async def update_customer_tier(self, stripe_customer_id, tier):
        self.tiers[stripe_customer_id] = tier

    async def deactivate_customer_keys(self, stripe_customer_id):
        self.deactivated.append(stripe_customer_id)

    async def reactivate_customer_keys(self, stripe_customer_id):
        self.reactivated.append(stripe_customer_id)

    async def set_customer_active(self, stripe_customer_id, active):
        self.active_state[stripe_customer_id] = active

    async def store_pending_key(self, session_id, raw_key, email, ttl_hours=24):
        self.pending_keys[session_id] = {"raw_key": raw_key, "email": email}

    async def claim_pending_key(self, session_id, email):
        entry = self.pending_keys.get(session_id)
        if entry is None or entry["email"] != email:
            return None
        return self.pending_keys.pop(session_id)["raw_key"]

    async def get_customer_by_id(self, customer_id):
        from link_content_scraper.auth import Customer
        data = self.customers.get(customer_id)
        if data is None:
            return None
        return Customer(
            stripe_customer_id=customer_id,
            email=data["email"],
            tier=data["tier"],
            active=True,
        )


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


# -- invoice.payment_succeeded -------------------------------------------------

class TestPaymentSucceeded:
    @pytest.mark.asyncio
    async def test_payment_succeeded_reactivates_customer(self, mock_db):
        event = _make_event("invoice.payment_succeeded", {
            "customer": "cus_abc",
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert mock_db.active_state.get("cus_abc") is True
        assert "cus_abc" in mock_db.reactivated

    @pytest.mark.asyncio
    async def test_payment_succeeded_missing_customer_id_skips_gracefully(self, mock_db):
        event = _make_event("invoice.payment_succeeded", {})
        with patch("stripe.Webhook.construct_event", return_value=event):
            # Should not raise
            await handle_webhook(b"payload", "sig")

        assert len(mock_db.active_state) == 0
        assert len(mock_db.reactivated) == 0


# -- Pending key delivery (Groups 2 & 3) ----------------------------------------

class TestCheckoutPendingKeyDelivery:
    @pytest.mark.asyncio
    async def test_checkout_stores_pending_key_with_email(self, mock_db):
        """checkout.session.completed must store the raw key in Supabase pending_keys."""
        event = _make_event("checkout.session.completed", {
            "id": "cs_test_session123",
            "customer": "cus_abc",
            "customer_email": "buyer@example.com",
            "metadata": {"tier": "starter"},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")

        assert "cs_test_session123" in mock_db.pending_keys
        assert mock_db.pending_keys["cs_test_session123"]["email"] == "buyer@example.com"

    @pytest.mark.asyncio
    async def test_pending_key_claim_requires_matching_email(self, mock_db):
        """claim_pending_key must return None when email does not match."""
        await mock_db.store_pending_key("cs_xyz", "secret_key_abc", "real@example.com")
        result = await mock_db.claim_pending_key("cs_xyz", "wrong@example.com")
        assert result is None
        assert "cs_xyz" in mock_db.pending_keys  # not consumed

    @pytest.mark.asyncio
    async def test_pending_key_claim_succeeds_with_correct_email(self, mock_db):
        """claim_pending_key returns raw key and removes it when email matches."""
        await mock_db.store_pending_key("cs_xyz", "secret_key_abc", "real@example.com")
        result = await mock_db.claim_pending_key("cs_xyz", "real@example.com")
        assert result == "secret_key_abc"
        assert "cs_xyz" not in mock_db.pending_keys  # consumed


# -- Idempotent webhook (Group 4) -----------------------------------------------

class TestCheckoutIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_webhook_does_not_create_second_customer(self, mock_db):
        """checkout.session.completed must be idempotent — second call skips customer creation."""
        event = _make_event("checkout.session.completed", {
            "id": "cs_test_idem",
            "customer": "cus_idem",
            "customer_email": "idem@example.com",
            "metadata": {"tier": "starter"},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")
            await handle_webhook(b"payload", "sig")

        assert len(mock_db.customers) == 1
        assert len(mock_db.api_keys) == 1

    @pytest.mark.asyncio
    async def test_duplicate_webhook_does_not_raise(self, mock_db):
        """Repeated checkout.session.completed must not raise — Stripe retries must get 200."""
        event = _make_event("checkout.session.completed", {
            "id": "cs_test_no_raise",
            "customer": "cus_no_raise",
            "customer_email": "raise@example.com",
            "metadata": {"tier": "starter"},
        })
        with patch("stripe.Webhook.construct_event", return_value=event):
            await handle_webhook(b"payload", "sig")
            # Should not raise on second call
            await handle_webhook(b"payload", "sig")
