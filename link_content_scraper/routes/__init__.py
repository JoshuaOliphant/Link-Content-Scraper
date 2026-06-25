# ABOUTME: Aggregates the domain routers into the single APIRouter the app mounts.
# ABOUTME: Submodules (meta, scrape, billing) each own one concern's HTTP handlers.
from fastapi import APIRouter

from . import billing, meta, scrape

router = APIRouter()
router.include_router(meta.router)
router.include_router(scrape.router)
router.include_router(billing.router)

__all__ = ["router", "meta", "scrape", "billing"]
