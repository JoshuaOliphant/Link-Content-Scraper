# ABOUTME: Application configuration loaded from environment variables with defaults.
# ABOUTME: Provides sensible defaults for rate limiting, timeouts, and file handling.
import os


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float_env(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


# Rate limiting & timeouts
RATE_LIMIT: int = _int_env("SCRAPER_RATE_LIMIT", 15)  # Reduce to 15 to be safer
RATE_PERIOD: int = _int_env("SCRAPER_RATE_PERIOD", 60)  # seconds
MAX_RETRIES: int = _int_env("SCRAPER_MAX_RETRIES", 3)
RETRY_DELAY: int = _int_env("SCRAPER_RETRY_DELAY", 5)  # seconds between retries
PDF_TIMEOUT: float = _float_env("SCRAPER_PDF_TIMEOUT", 60.0)  # Longer timeout for PDFs
DEFAULT_TIMEOUT: float = _float_env("SCRAPER_DEFAULT_TIMEOUT", 30.0)  # Default timeout for other content
BATCH_SIZE: int = _int_env("SCRAPER_BATCH_SIZE", 10)

# Title extraction & filenames
MAX_TITLE_SEARCH_LINES: int = _int_env("SCRAPER_MAX_TITLE_SEARCH_LINES", 30)
MIN_TITLE_LENGTH: int = _int_env("SCRAPER_MIN_TITLE_LENGTH", 3)
MAX_FILENAME_LENGTH: int = _int_env("SCRAPER_MAX_FILENAME_LENGTH", 100)
URL_HASH_LENGTH: int = _int_env("SCRAPER_URL_HASH_LENGTH", 12)

# Cleanup
CLEANUP_DELAY_SECONDS: int = _int_env("SCRAPER_CLEANUP_DELAY", 300)

# Logging
LOG_LEVEL: str = os.environ.get("SCRAPER_LOG_LEVEL", "INFO").upper()
