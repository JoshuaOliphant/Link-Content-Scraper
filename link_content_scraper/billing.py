# ABOUTME: Stripe billing integration — checkout sessions, customer portal, webhooks.
# ABOUTME: Handles subscription lifecycle events and provisions API keys on signup.

import hashlib
import logging
import secrets
from urllib.parse import quote

import stripe

from .auth import db_client
from .config import BASE_URL, STRIPE_PRICE_IDS as _STRIPE_PRICE_IDS_DEFAULT, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

# Module-level reference allows monkeypatching in tests
STRIPE_PRICE_IDS = _STRIPE_PRICE_IDS_DEFAULT

logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

_TIER_NAMES = {"starter", "pro", "business"}


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
        subscription_data={"metadata": {"tier": tier}},
        success_url=f"{BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}&email={quote(email)}",
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
    except stripe.error.SignatureVerificationError as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise ValueError(f"Invalid webhook signature: {e}") from e
    except ValueError as e:
        logger.warning("Stripe webhook payload is not valid JSON: %s", e)
        raise

    event_type = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")

    if event_type == "checkout.session.completed":
        await _on_checkout_completed(obj)
    elif event_type == "customer.subscription.updated":
        tier = obj.get("metadata", {}).get("tier")
        if not tier:
            logger.error(
                "subscription.updated for %s has no tier in metadata — refusing silent downgrade",
                customer_id,
            )
        else:
            await db_client.update_customer_tier(customer_id, tier)
            logger.info("Updated tier to %s for %s", tier, customer_id)
    elif event_type == "customer.subscription.deleted":
        await db_client.update_customer_tier(customer_id, "free")
        await db_client.deactivate_customer_keys(customer_id)
        logger.info("Subscription deleted for %s, downgraded to free", customer_id)
    elif event_type == "invoice.payment_succeeded":
        if not customer_id:
            logger.error("invoice.payment_succeeded missing 'customer' field — skipping reactivation")
        else:
            await db_client.set_customer_active(customer_id, True)
            await db_client.reactivate_customer_keys(customer_id)
            logger.info("Reactivated account for customer %s after successful payment", customer_id)
    elif event_type == "invoice.payment_failed":
        await db_client.deactivate_customer_keys(customer_id)
        logger.warning("Payment failed for %s, keys deactivated", customer_id)
    else:
        logger.debug("Unhandled Stripe event: %s", event_type)


async def _on_checkout_completed(obj: dict) -> None:
    session_id = obj.get("id", "")
    customer_id = obj.get("customer")
    if not customer_id:
        logger.error("checkout.session.completed missing 'customer' field: %s", obj)
        raise ValueError("Missing customer ID in checkout session")

    email = obj.get("customer_email", "")
    if not email:
        logger.error(
            "checkout.session.completed for customer %s missing customer_email — "
            "key delivery will fail without email second factor",
            customer_id,
        )

    tier = obj.get("metadata", {}).get("tier")
    if not tier:
        logger.error(
            "checkout.session.completed for customer %s missing tier metadata — "
            "defaulting to 'starter'",
            customer_id,
        )
        tier = "starter"

    existing = await db_client.get_customer_by_id(customer_id)
    if existing:
        has_key = await db_client.has_api_key_for_customer(customer_id)
        if has_key:
            # Both customer row and API key exist — fully provisioned on a prior run.
            logger.info("Webhook retry: customer %s already provisioned, skipping", customer_id)
            return
        # Customer row exists but key provisioning failed on a prior attempt — retry key steps only.
        logger.warning(
            "Webhook retry: customer %s exists but has no API key — continuing provisioning",
            customer_id,
        )
    else:
        try:
            await db_client.create_customer(customer_id, email, tier)
        except Exception as exc:
            logger.error("Failed to create customer %s: %s", customer_id, exc)
            raise

    raw_key, key_hash = _generate_api_key()
    try:
        await db_client.create_api_key(key_hash, customer_id)
    except Exception as exc:
        logger.error(
            "Failed to create API key for customer %s — manual remediation required: %s",
            customer_id,
            exc,
        )
        raise

    if session_id:
        await db_client.store_pending_key(session_id, raw_key, email)
    else:
        logger.error(
            "No session_id — API key for customer %s written to DB but cannot be delivered",
            customer_id,
        )

    logger.info("Provisioned API key for customer %s (tier=%s)", customer_id, tier)
