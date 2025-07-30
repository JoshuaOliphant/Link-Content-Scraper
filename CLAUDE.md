# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development
```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn main:app --reload

# Run server on specific port
uv run uvicorn main:app --reload --port 8080
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

This is a FastAPI web scraper application that fetches web pages and converts them to markdown using Jina Reader API.

### Key Components

- **FastAPI Application** (`main.py`): Single-file application with all endpoints and logic
- **Rate Limiting**: Token bucket implementation to respect Jina API limits (15 req/min)
- **Async Processing**: Uses httpx for concurrent HTTP requests with proper batching
- **Progress Tracking**: Server-sent events (SSE) for real-time progress updates
- **Content Processing**: Special handling for PDFs and arXiv papers

### Important Patterns

1. **URL Transformation**: arXiv URLs are automatically transformed to PDF versions for better content extraction
2. **Content Validation**: Scraped content is validated to ensure it's not empty or metadata-only
3. **Error Handling**: Implements retry logic with exponential backoff for failed requests
4. **Batch Processing**: Links are processed in batches of 10 with delays between batches
5. **Resource Cleanup**: Temporary files and ZIP archives are cleaned up after 5 minutes

### API Endpoints

- `GET /`: Serves the web interface
- `POST /api/scrape`: Starts a scraping job
- `GET /api/scrape/progress`: SSE endpoint for progress updates
- `GET /api/download/{job_id}`: Downloads scraped content as ZIP
- `POST /cancel/{tracker_id}`: Cancels an ongoing scraping operation

### Configuration Variables

Located in `main.py`:
- `RATE_LIMIT = 15`: Requests per minute to Jina API
- `RATE_PERIOD = 60`: Rate limit window in seconds
- `MAX_RETRIES = 3`: Number of retry attempts
- `RETRY_DELAY = 5`: Base delay between retries
- `PDF_TIMEOUT = 60.0`: Timeout for PDF content
- `DEFAULT_TIMEOUT = 30.0`: Default request timeout