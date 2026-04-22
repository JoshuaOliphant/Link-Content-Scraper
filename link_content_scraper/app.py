# ABOUTME: FastAPI application factory with middleware and exception handlers.
# ABOUTME: Creates and configures the Link Content Scraper web application.
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config as _config
from .config import LOG_LEVEL
from .routes import router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if not _config.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError(
            "STRIPE_WEBHOOK_SECRET must be set — refusing to start without webhook verification secret"
        )
    if not _config.STRIPE_SECRET_KEY:
        raise RuntimeError(
            "STRIPE_SECRET_KEY must be set — refusing to start without Stripe API key"
        )
    yield


def create_app() -> FastAPI:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if _config.SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(dsn=_config.SENTRY_DSN, traces_sample_rate=0.1)

    application = FastAPI(title="Link Content Scraper", lifespan=_lifespan)
    application.mount("/static", StaticFiles(directory="templates"), name="static")
    application.include_router(router)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logging.error("Validation error: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid URL format. Please ensure the URL starts with http:// or https://"
            },
        )

    return application
