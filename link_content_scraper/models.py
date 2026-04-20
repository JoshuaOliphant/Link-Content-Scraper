# ABOUTME: Pydantic request and response models for the scraping API.
# ABOUTME: Validates incoming URLs and structures outgoing scrape results.
from pydantic import BaseModel, AnyHttpUrl


class ScrapeRequest(BaseModel):
    url: AnyHttpUrl  # More lenient than HttpUrl — accepts a wider range of valid URLs


class ScrapeResponse(BaseModel):
    links: list[str]
    jobId: str
    trackerId: str
    successful: int = 0
    skipped: int = 0
    failed: int = 0
