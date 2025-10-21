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

### Testing
```bash
# Run title extraction tests
python test_title_extraction.py

# Run integration tests
python test_integration.py

# Run all tests
python test_title_extraction.py && python test_integration.py
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

- **FastAPI Application** (`main.py`): Single-file application (~500 lines) with all endpoints and logic
- **Rate Limiting**: Token bucket implementation to respect Jina API limits (15 req/min)
- **Async Processing**: Uses httpx for concurrent HTTP requests with proper batching
- **Progress Tracking**: Server-sent events (SSE) for real-time progress updates
- **Content Processing**: Special handling for PDFs and arXiv papers
- **Title Extraction**: Intelligent extraction of titles from markdown content for meaningful filenames
- **Testing**: Unit tests (`test_title_extraction.py`) and integration tests (`test_integration.py`)

### Important Patterns

1. **URL Transformation**: arXiv URLs are automatically transformed to PDF versions for better content extraction
2. **Content Validation**: Scraped content is validated to ensure it's not empty or metadata-only
3. **Error Handling**: Implements retry logic with exponential backoff for failed requests
4. **Batch Processing**: Links are processed in batches of 10 with delays between batches
5. **Resource Cleanup**: Temporary files and ZIP archives are cleaned up after 5 minutes
6. **Filename Generation**: Titles are extracted from content (H1, H2, or "Title:" format), sanitized, and combined with URL hash for unique, meaningful filenames

### API Endpoints

- `GET /`: Serves the web interface
- `POST /api/scrape`: Starts a scraping job
- `GET /api/scrape/progress`: SSE endpoint for progress updates
- `GET /api/download/{job_id}`: Downloads scraped content as ZIP
- `POST /cancel/{tracker_id}`: Cancels an ongoing scraping operation

### Configuration Variables

Located in `main.py`:

**Rate Limiting & Timeouts:**
- `RATE_LIMIT = 15`: Requests per minute to Jina API
- `RATE_PERIOD = 60`: Rate limit window in seconds
- `MAX_RETRIES = 3`: Number of retry attempts
- `RETRY_DELAY = 5`: Base delay between retries
- `PDF_TIMEOUT = 60.0`: Timeout for PDF content
- `DEFAULT_TIMEOUT = 30.0`: Default request timeout

**Title Extraction:**
- `MAX_TITLE_SEARCH_LINES = 30`: Lines to search for title in content
- `MIN_TITLE_LENGTH = 3`: Minimum characters for valid title
- `MAX_FILENAME_LENGTH = 100`: Maximum length before truncation
- `URL_HASH_LENGTH = 12`: Hash length appended to filenames

### Known Issues

- **Cancel Endpoint**: The `/cancel/{tracker_id}` endpoint is defined but the `cancel_scraping()` function is not implemented
- The progress tracker stores task references but cancellation logic needs to be added