# ABOUTME: Scraping-domain routes — start a job, stream progress, download, cancel.
# ABOUTME: Thin HTTP handlers that delegate to the scraper, job store, and tracker.
import hashlib
import logging
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ..auth import Customer, require_api_key
from ..jobs import job_store
from ..models import ScrapeRequest, ScrapeResponse
from ..progress import progress_tracker
from ..scraper import scrape_site
from ..usage import usage_recorder_for

logger = logging.getLogger(__name__)

router = APIRouter()


def _tracker_id_for(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


@router.post("/api/scrape", response_model=ScrapeResponse)
async def start_scraping(
    request: ScrapeRequest,
    customer: Customer = Depends(require_api_key),
):
    url = str(request.url)
    tracker_id = _tracker_id_for(url)
    job_id = str(uuid4())
    await job_store.claim_tracker(tracker_id, customer.stripe_customer_id)
    usage = usage_recorder_for(customer.stripe_customer_id)

    try:
        all_urls, zip_path = await scrape_site(url, tracker_id, job_id, usage)
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
    tracker_id = _tracker_id_for(url)
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
        media_type="application/zip",
        filename=f"scraped-content-{job_id}.zip",
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
