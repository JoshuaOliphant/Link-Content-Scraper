# Link Content Scraper

A FastAPI web application that scrapes content from web pages and their linked pages, converting them to clean markdown format using the Jina Reader API.

## Features

### Classic Scraper
- Scrapes content from a given URL and all its linked pages
- Converts web content to clean markdown using Jina's Reader API
- Handles PDF content (especially arXiv papers)
- Rate limiting to respect API limits
- Real-time progress tracking with SSE
- Downloads results as a ZIP file
- Filters out social media and image URLs
- Batched processing with configurable timeouts

### 🤖 NEW: AI Agent Mode
- **Prompt-native research workflows** - describe your goal in plain English
- **Intelligent content extraction** - AI-powered title extraction and classification
- **Batch analysis with synthesis** - compare multiple sources intelligently
- **Autonomous multi-step reasoning** - agent figures out how to accomplish tasks
- **Cost-optimized hybrid approach** - uses Claude Opus 4.5 + Haiku 4

👉 **Try it:** Visit `/agent` for the AI-powered interface!

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

## Deployment

### Quick Deploy to Fly.io

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
flyctl auth login

# Deploy
flyctl deploy
```

### Automatic Staging Deployments

Feature branches starting with `claude/**` automatically deploy to staging:
- **Staging URL:** https://link-content-scraper-staging.fly.dev/agent
- **Setup required:** Add `FLY_API_TOKEN` and `ANTHROPIC_API_KEY` to GitHub secrets

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed deployment instructions.

## Notes

- The application uses Jina's free Reader API which has a rate limit of 20 requests per minute
- PDF content (especially from arXiv) may take longer to process
- Some URLs may be filtered out to avoid rate limits and irrelevant content
- AI agent features require an Anthropic API key (set via `ANTHROPIC_API_KEY` environment variable)

## Documentation

- [QUICKSTART.md](./QUICKSTART.md) - Quick start guide for AI agent features
- [AGENT_README.md](./AGENT_README.md) - Technical documentation for AI architecture
- [DEPLOYMENT.md](./DEPLOYMENT.md) - Deployment guide for Fly.io
- [CHANGELOG.md](./CHANGELOG.md) - Version history and changes

## License

MIT
