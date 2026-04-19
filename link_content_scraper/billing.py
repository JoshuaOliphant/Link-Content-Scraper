# ABOUTME: Stripe billing integration — checkout sessions, customer portal, webhooks.
# ABOUTME: Handles subscription lifecycle events and provisions API keys on signup.

import hashlib
import logging
import secrets

import stripe

from .auth import db_client
from .config import BASE_URL, STRIPE_PRICE_IDS as _STRIPE_PRICE_IDS_DEFAULT, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

# Module-level reference allows monkeypatching in tests
STRIPE_PRICE_IDS = _STRIPE_PRICE_IDS_DEFAULT

logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

_TIER_NAMES = {"starter", "pro", "business"}

# Show-once key store: stripe_session_id -> raw_key (in-memory, single-instance safe)
_pending_keys: dict[str, str] = {}


def _generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, sha256_hash)."""
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


async def create_checkout_session(tier: str, email: str) -> str:
    """Create a Stripe Checkout session for the given tier. Returns redirect URL."""
    if tier not in _TIER_NAMES:
        raise ValueError(f"Unknown tier: {tier!r}. Must be one of {sorted(_TIER_NAMES)}")

    price_id = STRIPE_PRICE_IDS[tier]  # noqa: module-level ref allows test monkeypatching
    session = stripe.checkout.Session.create(
        customer_email=email,
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        metadata={"tier": tier},
        success_url=f"{BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/billing",
    )
    return session.url


async def create_portal_session(stripe_customer_id: str) -> str:
    """Create a Stripe Billing Portal session. Returns redirect URL."""
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=f"{BASE_URL}/billing",
    )
    return session.url


async def handle_webhook(payload: bytes, sig_header: str) -> None:
    """Verify and dispatch a Stripe webhook event."""
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise ValueError(f"Invalid webhook signature: {e}") from e

    event_type = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")

    if event_type == "checkout.session.completed":
        await _on_checkout_completed(obj)
    elif event_type == "customer.subscription.updated":
        tier = obj.get("metadata", {}).get("tier", "starter")
        await db_client.update_customer_tier(customer_id, tier)
        logger.info("Updated tier to %s for %s", tier, customer_id)
    elif event_type == "customer.subscription.deleted":
        await db_client.update_customer_tier(customer_id, "free")
        await db_client.deactivate_customer_keys(customer_id)
        logger.info("Subscription deleted for %s, downgraded to free", customer_id)
    elif event_type == "invoice.payment_failed":
        await db_client.deactivate_customer_keys(customer_id)
        logger.warning("Payment failed for %s, keys deactivated", customer_id)
    else:
        logger.debug("Unhandled Stripe event: %s", event_type)


def claim_pending_key(session_id: str) -> str | None:
    """Retrieve and delete a pending API key by Stripe session ID. Returns None if not found."""
    return _pending_keys.pop(session_id, None)


async def _on_checkout_completed(obj: dict) -> None:
    session_id = obj.get("id", "")
    customer_id = obj["customer"]
    email = obj.get("customer_email", "")
    tier = obj.get("metadata", {}).get("tier", "starter")

    await db_client.create_customer(customer_id, email, tier)

    raw_key, key_hash = _generate_api_key()
    await db_client.create_api_key(key_hash, customer_id)

    # Store raw key for one-time retrieval on the success page
    if session_id:
        _pending_keys[session_id] = raw_key

    logger.info("Provisioned API key for new customer %s (tier=%s)", customer_id, tier)
