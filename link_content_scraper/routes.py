import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .config import CLEANUP_DELAY_SECONDS
from .models import ScrapeRequest, ScrapeResponse
from .progress import progress_tracker
from .scraper import scrape_site

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store of job_id -> zip_path for downloads
_results: dict[str, str] = {}


@router.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=Path("templates/index.html").read_text())


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/api/scrape", response_model=ScrapeResponse)
async def start_scraping(request: ScrapeRequest):
    url = str(request.url)
    tracker_id = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    job_id = str(uuid4())

    try:
        all_urls, zip_path = await scrape_site(url, tracker_id, job_id)
        _results[job_id] = zip_path

        state = await progress_tracker.get(tracker_id)
        await progress_tracker.remove(tracker_id)

        return ScrapeResponse(
            links=all_urls,
            jobId=job_id,
            successful=state["successful"],
            skipped=state["skipped"],
            failed=state["failed"],
        )
    except Exception as e:
        await progress_tracker.remove(tracker_id)
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
async def download_results(job_id: str):
    if job_id not in _results:
        raise HTTPException(status_code=404, detail="Results not found")

    zip_path = _results[job_id]

    async def _cleanup():
        await asyncio.sleep(CLEANUP_DELAY_SECONDS)
        try:
            Path(zip_path).unlink(missing_ok=True)
            _results.pop(job_id, None)
        except OSError:
            logger.warning("Failed to clean up %s", zip_path)

    asyncio.create_task(_cleanup())

    return FileResponse(
        zip_path,
        media_type='application/zip',
        filename=f'scraped-content-{job_id}.zip',
    )


@router.post("/cancel/{tracker_id}")
async def cancel_scrape(tracker_id: str):
    cancelled = await progress_tracker.cancel(tracker_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Scraping operation not found")
    return JSONResponse({"status": "cancelled", "tracker_id": tracker_id})
