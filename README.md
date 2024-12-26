# Link Content Scraper

A FastAPI web application that scrapes content from web pages and their linked pages, converting them to clean markdown format using the Jina Reader API.

## Features

- Scrapes content from a given URL and all its linked pages
- Converts web content to clean markdown using Jina's Reader API
- Handles PDF content (especially arXiv papers)
- Rate limiting to respect API limits
- Real-time progress tracking with SSE
- Downloads results as a ZIP file
- Filters out social media and image URLs
- Batched processing with configurable timeouts

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) for dependency management
- Docker (optional)

## Installation

### Using uv (Recommended)

```bash
# Install dependencies
uv sync

# Activate virtual environment
uv venv

# Run the application
uvicorn main:app --reload
```

### Using Docker

```bash
# Build the image
docker build -t scraper .

# Run the container
docker run -p 8000:8000 scraper
```

## Usage

1. Open `http://localhost:8000` in your browser
2. Enter a URL to scrape
3. Watch the real-time progress
4. Download the results as a ZIP file when complete

## Configuration

The application has several configurable settings in `main.py`:

```python
RATE_LIMIT = 15          # Requests per minute
RATE_PERIOD = 60         # Seconds
MAX_RETRIES = 3          # Number of retries for failed requests
RETRY_DELAY = 5          # Seconds between retries
PDF_TIMEOUT = 60.0       # Timeout for PDF content (seconds)
DEFAULT_TIMEOUT = 30.0   # Default timeout (seconds)
```

## Dependencies

- `fastapi[standard]`: Web framework
- `httpx`: Async HTTP client
- `beautifulsoup4`: HTML parsing
- `aiofiles`: Async file operations
- `uvicorn`: ASGI server

## Development

The project uses modern Python tooling:
- `uv` for dependency management
- FastAPI for the web framework
- Docker with multi-stage builds
- Type hints throughout the codebase

## Notes

- The application uses Jina's free Reader API which has a rate limit of 20 requests per minute
- PDF content (especially from arXiv) may take longer to process
- Some URLs may be filtered out to avoid rate limits and irrelevant content

## License

MIT
