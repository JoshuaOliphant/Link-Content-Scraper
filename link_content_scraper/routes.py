# ABOUTME: API endpoint handlers for scraping, progress streaming, and downloads.
# ABOUTME: Defines all FastAPI routes and manages the job results store.
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import AnyHttpUrl, BaseModel

from .config import CLEANUP_DELAY_SECONDS
from .models import ScrapeRequest, ScrapeResponse
from .progress import progress_tracker
from .scraper import rate_limiter, scrape_site

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store of job_id -> zip_path for downloads, with lock protection
_results: dict[str, str] = {}
_results_lock = asyncio.Lock()


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
        async with _results_lock:
            _results[job_id] = zip_path

        state = await progress_tracker.get(tracker_id)
        await progress_tracker.remove(tracker_id)

        if state is None:
            logger.error("Progress tracker missing for %s before results could be read", tracker_id)
            state = {"successful": 0, "skipped": 0, "failed": 0}

        return ScrapeResponse(
            links=all_urls,
            jobId=job_id,
            successful=state["successful"],
            skipped=state["skipped"],
            failed=state["failed"],
        )
    except httpx.HTTPStatusError as e:
        await progress_tracker.remove(tracker_id)
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
    async with _results_lock:
        zip_path = _results.get(job_id)

    if zip_path is None:
        raise HTTPException(status_code=404, detail="Results not found")

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
async def cancel_scrape(tracker_id: str):
    cancelled = await progress_tracker.cancel(tracker_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Scraping operation not found")
    return JSONResponse({"status": "cancelled", "tracker_id": tracker_id})


# ── Agent endpoints ──────────────────────────────────────────────────────────

class QuickScrapeRequest(BaseModel):
    url: AnyHttpUrl


class ResearchRequest(BaseModel):
    goal: str
    urls: Optional[List[AnyHttpUrl]] = None


class BatchAnalysisRequest(BaseModel):
    urls: List[AnyHttpUrl]
    analysis_goal: str


_smart_scraper = None


def _get_smart_scraper():
    global _smart_scraper
    if _smart_scraper is None:
        from agent_system import SmartScraper
        _smart_scraper = SmartScraper(rate_limiter=rate_limiter.acquire)
    return _smart_scraper


@router.get("/agent", response_class=HTMLResponse)
async def agent_ui():
    return HTMLResponse(content=Path("templates/agent.html").read_text())


@router.post("/api/agent/quick-scrape")
async def agent_quick_scrape(request: QuickScrapeRequest):
    try:
        result = await _get_smart_scraper().quick_scrape(str(request.url))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agent/research")
async def agent_research(request: ResearchRequest):
    try:
        urls = [str(u) for u in request.urls] if request.urls else None
        result = await _get_smart_scraper().research_workflow(request.goal, urls)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agent/batch-analyze")
async def agent_batch_analyze(request: BatchAnalysisRequest):
    try:
        urls = [str(u) for u in request.urls]
        result = await _get_smart_scraper().batch_scrape_with_analysis(urls, request.analysis_goal)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/agent/examples")
async def agent_examples():
    return {
        "examples": [
            {
                "name": "Competitive Research",
                "goal": "Compare pricing and features of these competitor products",
                "description": "Analyzes multiple competitor sites and creates a comparison",
            },
            {
                "name": "Academic Research",
                "goal": "Summarize the key findings from these research papers",
                "description": "Extracts and synthesizes information from academic sources",
            },
            {
                "name": "Market Intelligence",
                "goal": "Identify trends and key themes across these industry blogs",
                "description": "Discovers patterns and insights across multiple sources",
            },
            {
                "name": "Due Diligence",
                "goal": "Research this company - find their team, funding, and product details",
                "description": "Comprehensive company research from public sources",
            },
        ]
    }
