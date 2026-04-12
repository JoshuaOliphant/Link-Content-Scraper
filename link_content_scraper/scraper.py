import asyncio
import logging
import shutil
import tempfile
import time
import zipfile
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
from .content import create_safe_filename, extract_title_from_content, is_content_valid
from .filters import is_pdf_url, should_skip_url, transform_arxiv_url
from .progress import progress_tracker
from .rate_limit import RateLimiter

logger = logging.getLogger(__name__)

rate_limiter = RateLimiter()


async def get_markdown_content(
    url: str,
    client: httpx.AsyncClient,
    tracker_id: str,
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

        except Exception as e:
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
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for md_file in temp_dir.glob('*.md'):
            zipf.write(md_file, md_file.name)

    shutil.rmtree(temp_dir)
    return str(zip_path), file_count


async def scrape_site(url: str, tracker_id: str, job_id: str) -> tuple[list[str], str]:
    """Scrape a URL and all its linked pages.

    Returns (list_of_all_urls, zip_path).
    """
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        # Fetch the original URL
        original_result = await get_markdown_content(url, client, tracker_id)
        results = [original_result]

        # Extract links from the raw HTML
        response = await client.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        links = [
            a['href'] for a in soup.find_all('a', href=True)
            if a['href'].startswith('http') and not should_skip_url(a['href'])
        ]

        await progress_tracker.init(tracker_id, total=len(links) + 1, processed=1)

        # Process in batches
        for i in range(0, len(links), BATCH_SIZE):
            if await progress_tracker.is_cancelled(tracker_id):
                break

            batch = links[i:i + BATCH_SIZE]
            tasks = [
                asyncio.create_task(get_markdown_content(link, client, tracker_id))
                for link in batch
            ]
            await progress_tracker.register_tasks(tracker_id, tasks)
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in batch_results:
                if isinstance(result, tuple):
                    results.append(result)

            if i + BATCH_SIZE < len(links):
                await asyncio.sleep(RATE_PERIOD / 2)

        zip_path, confirmed = create_zip_file(results, job_id)
        await progress_tracker.update(tracker_id, successful=confirmed)
        return [url] + links, zip_path
