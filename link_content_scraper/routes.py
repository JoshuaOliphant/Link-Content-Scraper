# ABOUTME: API endpoint handlers for scraping, progress streaming, and downloads.
# ABOUTME: Defines all FastAPI routes and manages the job results store.
import hashlib
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr

from . import config as _config
from .auth import Customer, db_client, require_api_key
from .billing import create_checkout_session, create_portal_session, handle_webhook
from .config import TIER_LIMITS
from .jobs import job_store
from .models import ScrapeRequest, ScrapeResponse
from .progress import progress_tracker
from .scraper import scrape_site

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=Path("templates/index.html").read_text())


@router.get("/health")
async def health():
    issues = []
    if not _config.SUPABASE_URL:
        issues.append("SUPABASE_URL not configured")
    if not _config.SUPABASE_KEY:
        issues.append("SUPABASE_KEY not configured")
    if issues:
        return JSONResponse(status_code=500, content={"status": "error", "issues": issues})
    return JSONResponse({"status": "ok"})


@router.post("/api/scrape", response_model=ScrapeResponse)
async def start_scraping(
    request: ScrapeRequest,
    customer: Customer = Depends(require_api_key),
):
    url = str(request.url)
    tracker_id = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    job_id = str(uuid4())
    await job_store.claim_tracker(tracker_id, customer.stripe_customer_id)

    try:
        all_urls, zip_path = await scrape_site(url, tracker_id, job_id, customer.stripe_customer_id)
        await job_store.store_result(job_id, zip_path, customer.stripe_customer_id)
        await job_store.release_tracker(tracker_id)

        state = await progress_tracker.get(tracker_id)
        await progress_tracker.remove(tracker_id)

        if state is None:
            logger.error("Progress tracker missing for %s before results could be read", tracker_id)
            state = {"successful": 0, "skipped": 0, "failed": 0}

        return ScrapeResponse(
            links=all_urls,
            jobId=job_id,
            trackerId=tracker_id,
            successful=state["successful"],
            skipped=state["skipped"],
            failed=state["failed"],
        )
    except httpx.HTTPStatusError as e:
        await progress_tracker.remove(tracker_id)
        await job_store.release_tracker(tracker_id)
        code = e.response.status_code
        if code == 403:
            detail = "The target site returned 403 Forbidden — it may be blocking automated access."
        elif code == 404:
            detail = "The target URL returned 404 Not Found — check that the URL is correct."
        else:
            detail = f"The target site returned HTTP {code}."
        logger.warning("Upstream HTTP %d for %s", code, url)
        raise HTTPException(status_code=502, detail=detail)
    except (httpx.HTTPError, ValueError, OSError) as e:
        await progress_tracker.remove(tracker_id)
        await job_store.release_tracker(tracker_id)
        logger.exception("Scrape failed for %s", url)
        raise HTTPException(status_code=500, detail=f"Error scraping URL: {e}")


@router.get("/api/scrape/progress")
async def scrape_progress(url: str):
    tracker_id = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    return StreamingResponse(
        progress_tracker.generate_events(tracker_id),
        media_type="text/event-stream",
    )


@router.get("/api/download/{job_id}")
async def download_results(job_id: str, customer: Customer = Depends(require_api_key)):
    entry = await job_store.get_result(job_id, customer.stripe_customer_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Results not found")

    job_store.schedule_cleanup(job_id, entry.zip_path)

    return FileResponse(
        entry.zip_path,
        media_type='application/zip',
        filename=f'scraped-content-{job_id}.zip',
    )


@router.post("/cancel/{tracker_id}")
async def cancel_scrape(tracker_id: str, customer: Customer = Depends(require_api_key)):
    owner = await job_store.tracker_owner(tracker_id)
    if owner is not None and owner != customer.stripe_customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this operation")
    cancelled = await progress_tracker.cancel(tracker_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Scraping operation not found")
    await job_store.release_tracker(tracker_id)
    return JSONResponse({"status": "cancelled", "tracker_id": tracker_id})


# -- Billing routes ------------------------------------------------------------

class CheckoutRequest(BaseModel):
    tier: str
    email: str


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


class FreeSignupRequest(BaseModel):
    email: EmailStr


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
