import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_SKIP_PATTERNS = [
    re.compile(p) for p in [
        r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$', r'\.webp$',
        r'twitter\.com', r'x\.com',
        r'linkedin\.com',
        r'facebook\.com',
        r'instagram\.com',
        r'youtube\.com',
        r'substackcdn\.com',
    ]
]

_ARXIV_PATTERNS = [
    re.compile(p) for p in [
        r'arxiv\.org/abs/(\d+\.\d+)(v\d+)?',
        r'arxiv\.org/pdf/(\d+\.\d+)(v\d+)?\.pdf',
        r'arxiv\.org/html/(\d+\.\d+)(v\d+)?',
    ]
]


def should_skip_url(url: str) -> bool:
    """Return True if the URL points to social media, images, or other non-article content."""
    lower = url.lower()
    return any(p.search(lower) for p in _SKIP_PATTERNS)


def transform_arxiv_url(url: str) -> str:
    """Convert arXiv abstract/HTML URLs to their PDF equivalents for better extraction."""
    for pattern in _ARXIV_PATTERNS:
        match = pattern.search(url)
        if match:
            paper_id = match.group(1)
            version = match.group(2) or ''
            transformed = f"https://arxiv.org/pdf/{paper_id}{version}.pdf"
            logger.info("Transformed arXiv URL: %s -> %s", url, transformed)
            return transformed
    return url


def is_pdf_url(url: str) -> bool:
    lower = url.lower()
    return lower.endswith('.pdf') or 'arxiv.org/pdf' in lower
