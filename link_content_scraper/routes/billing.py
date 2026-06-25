# ABOUTME: Billing & account routes — checkout, portal, usage status, webhooks, signup.
# ABOUTME: Thin HTTP handlers delegating to the Stripe and Supabase service layers.
import hashlib
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr

from .. import config as _config
from ..auth import Customer, db_client, require_api_key
from ..billing import create_checkout_session, create_portal_session, handle_webhook
from ..config import TIER_LIMITS

logger = logging.getLogger(__name__)

router = APIRouter()


class CheckoutRequest(BaseModel):
    tier: str
    email: str


class FreeSignupRequest(BaseModel):
    email: EmailStr


@router.get("/billing", response_class=HTMLResponse)
async def billing_page():
    return HTMLResponse(content=Path("templates/billing.html").read_text())


@router.get("/billing/success", response_class=HTMLResponse)
async def billing_success():
    return HTMLResponse(content=Path("templates/billing_success.html").read_text())


@router.post("/api/billing/checkout")
async def checkout(request: CheckoutRequest):
    url = await create_checkout_session(request.tier, request.email)
    return JSONResponse({"url": url})


@router.get("/billing/portal")
async def portal(customer: Customer = Depends(require_api_key)):
    url = await create_portal_session(customer.stripe_customer_id)
    return JSONResponse({"url": url})


@router.get("/api/billing/status")
async def billing_status(customer: Customer = Depends(require_api_key)):
    month = datetime.now(UTC).strftime("%Y-%m")
    usage = await db_client.get_usage(customer.stripe_customer_id, month)
    limit = TIER_LIMITS.get(customer.tier, 0)
    return JSONResponse({
        "tier": customer.tier,
        "usage": usage,
        "limit": limit,
        "month": month,
    })


@router.post("/api/webhooks/stripe")
async def stripe_webhook(raw_request: Request):
    payload = await raw_request.body()
    sig_header = raw_request.headers.get("stripe-signature", "")
    try:
        await handle_webhook(payload, sig_header)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"status": "ok"})


@router.get("/api/billing/key")
async def get_pending_key(session_id: str, email: str):
    """Retrieve a newly generated API key. Requires session_id and email as second factor."""
    key = await db_client.claim_pending_key(session_id, email)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found or already retrieved")
    return JSONResponse({"key": key})


@router.post("/api/signup/free")
async def signup_free(request: FreeSignupRequest):
    """Provision a free-tier API key immediately — no payment required."""
    email = request.email.strip().lower()

    existing = await db_client.get_customer_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    customer_id = f"free_{uuid4().hex}"
    try:
        await db_client.create_customer(customer_id, email, "free")

        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        await db_client.create_api_key(key_hash, customer_id)

        session_id = f"free_{uuid4().hex}"
        await db_client.store_pending_key(session_id, raw_key, email)
    except Exception:
        logger.exception(
            "Free signup failed mid-flight for customer %s (email=%s) — attempting rollback",
            customer_id, email,
        )
        try:
            await db_client.delete_customer(customer_id)
        except Exception:
            logger.error(
                "Rollback failed for partial free signup customer %s — manual cleanup required",
                customer_id,
            )
        raise HTTPException(status_code=500, detail="Account creation failed. Please try again.")

    redirect_url = (
        f"{_config.BASE_URL}/billing/success"
        f"?session_id={quote(session_id)}&email={quote(email)}"
    )
    return JSONResponse({"redirectUrl": redirect_url})
