# ABOUTME: API endpoint handlers for scraping, progress streaming, and downloads.
# ABOUTME: Defines all FastAPI routes and manages the job results store.
import asyncio
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
from pydantic import BaseModel

from . import config as _config
from .auth import Customer, db_client, require_api_key
from .billing import create_checkout_session, create_portal_session, handle_webhook
from .config import CLEANUP_DELAY_SECONDS, TIER_LIMITS
from .models import ScrapeRequest, ScrapeResponse
from .progress import progress_tracker
from .scraper import rate_limiter, scrape_site

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store of job_id -> {zip_path, customer_id}, with lock protection
_results: dict[str, dict] = {}
_results_lock = asyncio.Lock()

# Tracks which customer started each scrape job (tracker_id -> customer_id)
_tracker_owners: dict[str, str] = {}


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
    _tracker_owners[tracker_id] = customer.stripe_customer_id

    try:
        all_urls, zip_path = await scrape_site(url, tracker_id, job_id, customer.stripe_customer_id)
        async with _results_lock:
            _results[job_id] = {"zip_path": zip_path, "customer_id": customer.stripe_customer_id}
        _tracker_owners.pop(tracker_id, None)

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
        _tracker_owners.pop(tracker_id, None)
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
        _tracker_owners.pop(tracker_id, None)
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
    async with _results_lock:
        entry = _results.get(job_id)

    if entry is None or entry["customer_id"] != customer.stripe_customer_id:
        raise HTTPException(status_code=404, detail="Results not found")

    zip_path = entry["zip_path"]

    async def _cleanup():
        await asyncio.sleep(CLEANUP_DELAY_SECONDS)
        try:
            Path(zip_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to clean up %s", zip_path)
        finally:
            async with _results_lock:
                _results.pop(job_id, None)

    asyncio.create_task(_cleanup())

    return FileResponse(
        zip_path,
        media_type='application/zip',
        filename=f'scraped-content-{job_id}.zip',
    )


@router.post("/cancel/{tracker_id}")
async def cancel_scrape(tracker_id: str, customer: Customer = Depends(require_api_key)):
    owner = _tracker_owners.get(tracker_id)
    if owner is not None and owner != customer.stripe_customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this operation")
    cancelled = await progress_tracker.cancel(tracker_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Scraping operation not found")
    _tracker_owners.pop(tracker_id, None)
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
    email: str


@router.post("/api/signup/free")
async def signup_free(request: FreeSignupRequest):
    """Provision a free-tier API key immediately — no payment required."""
    email = request.email.strip().lower()

    existing = await db_client.get_customer_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    customer_id = f"free_{uuid4().hex}"
    await db_client.create_customer(customer_id, email, "free")

    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    await db_client.create_api_key(key_hash, customer_id)

    session_id = f"free_{uuid4().hex}"
    await db_client.store_pending_key(session_id, raw_key, email)

    redirect_url = (
        f"{_config.BASE_URL}/billing/success"
        f"?session_id={quote(session_id)}&email={quote(email)}"
    )
    return JSONResponse({"redirectUrl": redirect_url})
