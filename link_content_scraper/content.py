import hashlib
import logging
import re
import unicodedata
from typing import Optional

from .config import MAX_TITLE_SEARCH_LINES, MIN_TITLE_LENGTH, MAX_FILENAME_LENGTH, URL_HASH_LENGTH

logger = logging.getLogger(__name__)

METADATA_PREFIXES = ("# Original URL:", "Title:", "URL Source:", "Markdown Content:")


def _clean_title(title: str) -> str:
    """Remove markdown link and emphasis formatting from a title string."""
    title = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', title)
    title = re.sub(r'[*_`]', '', title)
    return title.strip()


def extract_title_from_content(content: str) -> Optional[str]:
    """Extract a human-readable title from Jina-returned markdown.

    Searches the first MAX_TITLE_SEARCH_LINES for an H1, a "Title:" line,
    or (as fallback) an H2 header.
    """
    if not content:
        return None

    lines = content.split('\n')

    for line in lines[:MAX_TITLE_SEARCH_LINES]:
        line = line.strip()
        if not line:
            continue
        if line.startswith(METADATA_PREFIXES):
            if line.startswith('Title:') and len(line) > 7:
                title = line[6:].strip()
                if title:
                    return title
            continue
        if line.startswith('# ') and len(line) > 2:
            title = _clean_title(line[2:])
            if title and len(title) > MIN_TITLE_LENGTH:
                return title

    # Fallback: look for H2
    for line in lines[:MAX_TITLE_SEARCH_LINES]:
        line = line.strip()
        if line.startswith('## ') and len(line) > 3:
            title = _clean_title(line[3:])
            if title and len(title) > MIN_TITLE_LENGTH:
                return title

    return None


def create_safe_filename(title: Optional[str], url: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Create a filesystem-safe filename from a title and URL.

    Always appends a short URL hash for uniqueness.
    """
    url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()[:URL_HASH_LENGTH]

    if not title:
        return f"{url_hash}.md"

    normalized = unicodedata.normalize('NFKD', title)
    ascii_title = normalized.encode('ascii', 'ignore').decode('ascii')
    safe_chars = re.sub(r'[^\w\s-]', '', ascii_title)
    safe_chars = re.sub(r'[-\s]+', '-', safe_chars).strip('-')

    if len(safe_chars) > max_length:
        safe_chars = safe_chars[:max_length].rstrip('-')

    if not safe_chars:
        return f"untitled_{url_hash}.md"

    return f"{safe_chars}_{url_hash}.md"


def is_content_valid(content: str) -> bool:
    """Return True if scraped content has real substance (not just metadata)."""
    if not content or len(content.strip()) < 50 or content.count('\n') < 3:
        return False
    lines = content.split('\n')
    return not all(
        line.startswith(METADATA_PREFIXES) for line in lines if line.strip()
    )
