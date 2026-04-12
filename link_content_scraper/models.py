from pydantic import BaseModel, AnyHttpUrl


class ScrapeRequest(BaseModel):
    url: AnyHttpUrl


class ScrapeResponse(BaseModel):
    links: list[str]
    jobId: str
    successful: int = 0
    skipped: int = 0
    failed: int = 0
