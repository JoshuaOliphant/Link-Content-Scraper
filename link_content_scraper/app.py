import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import LOG_LEVEL
from .routes import router


def create_app() -> FastAPI:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    application = FastAPI(title="Link Content Scraper")
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
