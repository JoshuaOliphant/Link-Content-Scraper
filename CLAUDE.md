# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development
```bash
# Install dependencies (including dev extras)
uv sync --extra dev

# Run development server
uv run uvicorn main:app --reload

# Run server on specific port
uv run uvicorn main:app --reload --port 8080
```

### Testing
```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_content.py

# Run a specific test class or method
uv run pytest tests/test_routes.py::TestHealthEndpoint
```

### Docker
```bash
# Build Docker image
docker build -t link-content-scraper .

# Run Docker container
docker run -p 8080:8080 link-content-scraper
```

### Deployment
```bash
# Deploy to Fly.io
fly deploy
```

## Architecture

FastAPI web scraper that fetches web pages and converts them to markdown using Jina Reader API.

### Package Layout

```
link_content_scraper/
  app.py          # FastAPI factory (create_app), middleware, exception handlers
  config.py       # All settings loaded from environment variables with defaults
  models.py       # Pydantic request/response models
  content.py      # Title extraction, filename generation, content validation
  filters.py      # URL skip-list and arXiv URL transformation
  rate_limit.py   # Async-safe timestamp-based rate limiter
  progress.py     # Async-safe progress tracking with SSE event generation
  jobs.py         # JobStore: async-safe results store, ownership, ZIP cleanup
  usage.py        # UsageRecorder seam — meters usage without coupling to storage
  scraper.py      # Core scraping logic (Jina API calls, ZIP creation)
  auth.py         # API-key auth dependency + Supabase database client
  billing.py      # Stripe checkout/portal/webhook service layer
  routes/         # HTTP handlers, one submodule per domain
    __init__.py   #   aggregates the submodule routers into one APIRouter
    meta.py       #   index page + health check
    scrape.py     #   scrape, progress stream, download, cancel
    billing.py    #   checkout, portal, usage status, webhook, signup
main.py           # Thin entry point (uvicorn main:app)
tests/            # pytest test suite
```

### Key Design Decisions

- **Async-safe shared state**: `ProgressTracker` uses `asyncio.Lock` so concurrent tasks can safely update counters.
- **Rate limiter**: `RateLimiter` class with lock-protected timestamp tracking.
- **Job lifecycle**: `JobStore` (jobs.py) owns the completed-job results store, tracker
  ownership, and delayed ZIP cleanup — keeping that state out of the route handlers.
- **Decoupled metering**: the scraper records usage through the `UsageRecorder`
  protocol (usage.py); it has no direct dependency on auth/Supabase. Routes inject a
  `DbUsageRecorder` via `usage_recorder_for()`.
- **Domain-split routes**: handlers live in the `routes/` package, one submodule per
  concern (meta/scrape/billing), aggregated into a single router by `routes/__init__.py`.
- **Config via env vars**: Every setting in `config.py` reads from an environment variable with a sensible default. No rebuild needed to tune.
- **Cancellation**: `POST /cancel/{tracker_id}` marks the tracker cancelled and cancels in-flight asyncio tasks.
- **Content validation**: Shared `is_content_valid()` used by both the fetcher and ZIP creator.

### API Endpoints

- `GET /` — Web interface
- `GET /health` — Health check for load balancers
- `POST /api/scrape` — Start a scraping job
- `GET /api/scrape/progress?url=` — SSE progress stream
- `GET /api/download/{job_id}` — Download results as ZIP
- `POST /cancel/{tracker_id}` — Cancel an in-progress scrape

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SCRAPER_RATE_LIMIT` | 15 | Max requests per window |
| `SCRAPER_RATE_PERIOD` | 60 | Rate limit window (seconds) |
| `SCRAPER_MAX_RETRIES` | 3 | Retry attempts per URL |
| `SCRAPER_RETRY_DELAY` | 5 | Base retry delay (seconds) |
| `SCRAPER_PDF_TIMEOUT` | 60.0 | Timeout for PDF fetches |
| `SCRAPER_DEFAULT_TIMEOUT` | 30.0 | Default request timeout |
| `SCRAPER_BATCH_SIZE` | 10 | URLs per batch |
| `SCRAPER_CLEANUP_DELAY` | 300 | Seconds before temp files are deleted |
| `SCRAPER_LOG_LEVEL` | INFO | Python log level |
