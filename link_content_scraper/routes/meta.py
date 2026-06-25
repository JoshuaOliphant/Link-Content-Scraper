# ABOUTME: Site-level routes — the web UI entry point and the health check.
# ABOUTME: No domain logic; just serves the index page and reports config status.
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from .. import config as _config

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
