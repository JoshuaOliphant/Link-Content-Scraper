# ABOUTME: Core scraping logic — fetches URLs via Jina Reader API with retries.
# ABOUTME: Handles batched processing, cancellation, and ZIP file creation.
import asyncio
import logging
import shutil
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .config import (
    BATCH_SIZE,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    PDF_TIMEOUT,
    RATE_PERIOD,
    RETRY_DELAY,
)
from .auth import db_client
from .content import create_safe_filename, extract_title_from_content, is_content_valid
from .filters import is_pdf_url, should_skip_url, transform_arxiv_url
from .progress import progress_tracker
from .rate_limit import RateLimiter

logger = logging.getLogger(__name__)

rate_limiter = RateLimiter()

_BOILERPLATE_TAGS = frozenset({'header', 'footer', 'nav', 'aside'})


def extract_content_links(soup: BeautifulSoup) -> list[str]:
    """Extract links from the main content area, ignoring navigation chrome.

    Prefers <main>, <article>, or role="main". Falls back to full document
    minus <header>, <footer>, <nav>, <aside>. Deduplicates preserving order.
    """
    content = (
        soup.find('main')
        or soup.find('article')
        or soup.find(attrs={'role': 'main'})
    )
    if content is not None:
        anchors = content.find_all('a', href=True)
    else:
        anchors = [
            a for a in soup.find_all('a', href=True)
            if not any(a.find_parent(tag) for tag in _BOILERPLATE_TAGS)
        ]
    return list(dict.fromkeys(a['href'] for a in anchors))


async def get_markdown_content(
    url: str,
    client: httpx.AsyncClient,
    tracker_id: str,
    customer_id: str | None = None,
) -> tuple[str, str]:
    """Fetch markdown for a single URL via the Jina Reader API.

    Returns (original_url, markdown_content).  Content is empty string on
    skip or failure.
    """
    await progress_tracker.update(tracker_id, current_url=url)

    if should_skip_url(url):
        await progress_tracker.increment(tracker_id, processed=1, skipped=1)
        return url, ""

    if await progress_tracker.is_cancelled(tracker_id):
        return url, ""

    transformed_url = transform_arxiv_url(url)
    if transformed_url != url:
        logger.info("URL transformation: %s -> %s", url, transformed_url)

    is_pdf = is_pdf_url(transformed_url)
    timeout = PDF_TIMEOUT if is_pdf else DEFAULT_TIMEOUT

    start_time = time.time()
    retries = 0

    while retries <= MAX_RETRIES:
        if await progress_tracker.is_cancelled(tracker_id):
            return url, ""
        try:
            await rate_limiter.acquire()

            jina_url = f"https://r.jina.ai/{transformed_url}"
            logger.info("Fetching: %s", jina_url)

            response = await client.get(jina_url, timeout=timeout)

            if response.status_code == 200:
                content = response.text.strip()

                if not is_content_valid(content):
                    raise ValueError("Retrieved content too short or metadata-only")

                elapsed = time.time() - start_time
                logger.info("Fetched %s in %.2fs (%d chars)", url, elapsed, len(content))
                await progress_tracker.increment(tracker_id, processed=1, potential_successful=1)
                if customer_id:
                    month = datetime.now(UTC).strftime("%Y-%m")
                    try:
                        await db_client.increment_usage(customer_id, month)
                    except Exception as exc:
                        logger.error(
                            "Failed to increment usage for %s month %s url %s: %s",
                            customer_id,
                            month,
                            url,
                            exc,
                        )
                return url, content

            if response.status_code == 429:
                retries += 1
                if retries <= MAX_RETRIES:
                    wait_time = RETRY_DELAY * retries
                    logger.warning("Rate-limited on %s, waiting %ds", url, wait_time)
                    await asyncio.sleep(wait_time)
                    continue

            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}",
                request=response.request,
                response=response,
            )

        except (httpx.HTTPError, ValueError) as e:
            # Retry network errors and content validation failures only
            retries += 1
            if retries <= MAX_RETRIES:
                wait_time = RETRY_DELAY * retries
                logger.warning("Error on %s (attempt %d/%d): %s", url, retries, MAX_RETRIES, e)
                await asyncio.sleep(wait_time)
                continue
            logger.error("Failed %s after %d retries: %s", url, MAX_RETRIES, e)
            break

    await progress_tracker.increment(tracker_id, processed=1, failed=1)
    return url, ""


def create_zip_file(
    contents: list[tuple[str, str]],
    job_id: str,
) -> tuple[str, int]:
    """Write valid scraped content into a ZIP of markdown files.

    Returns (zip_path, confirmed_success_count).
    Raises if no valid content exists.
    """
    temp_dir = Path(tempfile.gettempdir()) / job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    file_count = 0
    for url, content in contents:
        if not content or not is_content_valid(content):
            continue

        title = extract_title_from_content(content)
        safe_filename = create_safe_filename(title, url)
        logger.info("Writing %s for %s", safe_filename, url)

        file_path = temp_dir / safe_filename
        file_path.write_text(f"# Original URL: {url}\n\n{content}", encoding="utf-8")
        file_count += 1

    if file_count == 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ValueError("No valid content to download")

    zip_path = temp_dir.parent / f"{job_id}.zip"
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for md_file in temp_dir.glob('*.md'):
                zipf.write(md_file, md_file.name)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return str(zip_path), file_count


async def scrape_site(
    url: str,
    tracker_id: str,
    job_id: str,
    customer_id: str | None = None,
) -> tuple[list[str], str]:
    """Scrape a URL and all its linked pages.

    Returns (list_of_all_urls, zip_path).
    """
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        # Fetch the original URL
        original_result = await get_markdown_content(url, client, tracker_id, customer_id)
        results = [original_result]

        # Extract links from the main content area only
        response = await client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        links = [
            href for href in extract_content_links(soup)
            if href.startswith('http') and not should_skip_url(href)
        ]

        await progress_tracker.init(tracker_id, total=len(links) + 1, processed=1)

        # Process in batches
        for i in range(0, len(links), BATCH_SIZE):
            if await progress_tracker.is_cancelled(tracker_id):
                break

            batch = links[i:i + BATCH_SIZE]
            tasks = [
                asyncio.create_task(get_markdown_content(link, client, tracker_id, customer_id))
                for link in batch
            ]
            await progress_tracker.register_tasks(tracker_id, tasks)
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in batch_results:
                if isinstance(result, tuple):
                    results.append(result)
                elif isinstance(result, BaseException):
                    logger.error("Unhandled task exception: %s", result)
                    await progress_tracker.increment(tracker_id, processed=1, failed=1)

            if i + BATCH_SIZE < len(links):
                await asyncio.sleep(RATE_PERIOD / 2)  # Wait 30 seconds between batches

        zip_path, confirmed = create_zip_file(results, job_id)
        await progress_tracker.update(tracker_id, successful=confirmed)
        return [url] + links, zip_path
