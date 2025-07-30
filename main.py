from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, HttpUrl, AnyHttpUrl
from pathlib import Path
import httpx
import asyncio
from bs4 import BeautifulSoup
import logging
import json
from collections import defaultdict
import zipfile
from uuid import uuid4
import tempfile
import shutil
import time
from asyncio import Semaphore, CancelledError, Task
import re
from urllib.parse import urlparse
from typing import Dict, Optional
import unicodedata

# Rate limiting settings
RATE_LIMIT = 15  # Reduce to 15 to be safer
RATE_PERIOD = 60  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries
PDF_TIMEOUT = 60.0  # Longer timeout for PDFs
DEFAULT_TIMEOUT = 30.0  # Default timeout for other content
rate_limit_semaphore = Semaphore(RATE_LIMIT)
last_request_times = []

logging.basicConfig(level=logging.INFO)

def extract_title_from_content(content: str) -> Optional[str]:
    """Extract title from the markdown content returned by Jina API"""
    if not content:
        return None
    
    lines = content.split('\n')
    
    # Debug: log first few lines to understand content structure
    logging.debug(f"First 10 lines of content: {lines[:10]}")
    
    # Look for markdown headers
    for line in lines[:30]:  # Check first 30 lines
        line = line.strip()
        
        # Skip empty lines
        if not line:
            continue
        
        # Skip metadata lines
        if line.startswith(('URL Source:', 'Markdown Content:', '# Original URL:', 'Published:')):
            continue
            
        # Look for H1 headers
        if line.startswith('# ') and len(line) > 2:
            title = line[2:].strip()
            # Clean up the title - remove any markdown formatting
            title = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', title)  # Remove links
            title = re.sub(r'[*_`]', '', title)  # Remove emphasis markers
            if title and len(title) > 3:  # Ensure it's not too short
                logging.debug(f"Found H1 title: {title}")
                return title
                
        # Sometimes title is in format "Title: Some Title"
        if line.startswith('Title:') and len(line) > 7:
            title = line[6:].strip()
            if title:
                logging.debug(f"Found Title: format: {title}")
                return title
    
    # Look for H2 headers if no H1 found
    for line in lines[:30]:
        line = line.strip()
        if line.startswith('## ') and len(line) > 3:
            title = line[3:].strip()
            # Clean up the title
            title = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', title)
            title = re.sub(r'[*_`]', '', title)
            if title and len(title) > 3:
                logging.debug(f"Found H2 title: {title}")
                return title
    
    logging.debug("No title found in content")
    return None

def create_safe_filename(title: str, url: str, max_length: int = 100) -> str:
    """Create a safe filename from title and URL"""
    if not title:
        # Fallback to URL hash if no title
        return f"{hash(url)}.md"
    
    # Remove or replace unsafe characters
    # First, normalize unicode characters
    title = unicodedata.normalize('NFKD', title)
    title = title.encode('ascii', 'ignore').decode('ascii')
    
    # Replace spaces and special characters
    safe_chars = re.sub(r'[^\w\s-]', '', title)
    safe_chars = re.sub(r'[-\s]+', '-', safe_chars)
    
    # Remove leading/trailing hyphens
    safe_chars = safe_chars.strip('-')
    
    # Truncate if too long
    if len(safe_chars) > max_length:
        safe_chars = safe_chars[:max_length].rstrip('-')
    
    # Add a short hash to ensure uniqueness
    url_hash = str(abs(hash(url)))[:8]
    
    # Handle empty result
    if not safe_chars:
        return f"untitled_{url_hash}.md"
    
    return f"{safe_chars}_{url_hash}.md"

def should_skip_url(url: str) -> bool:
    """Check if URL should be skipped based on patterns"""
    parsed = urlparse(url)
    
    # Skip social media and image URLs
    skip_patterns = [
        r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$', r'\.webp$',
        r'twitter\.com', r'x\.com',
        r'linkedin\.com',
        r'facebook\.com',
        r'instagram\.com',
        r'youtube\.com',
        r'substackcdn\.com'
    ]
    
    return any(re.search(pattern, url.lower()) for pattern in skip_patterns)

def transform_arxiv_url(url: str) -> str:
    """Transform arXiv URLs to get PDF content instead of abstract"""
    # Log original URL
    logging.info(f"Checking if URL is arXiv: {url}")
    
    # Handle multiple arXiv URL patterns
    arxiv_patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)(v\d+)?',
        r'arxiv\.org/pdf/(\d+\.\d+)(v\d+)?\.pdf',
        r'arxiv\.org/html/(\d+\.\d+)(v\d+)?',
    ]
    
    for pattern in arxiv_patterns:
        match = re.search(pattern, url)
        if match:
            paper_id = match.group(1)
            version = match.group(2) if match.group(2) else ''
            transformed_url = f"https://arxiv.org/pdf/{paper_id}{version}.pdf"
            logging.info(f"Transformed arXiv URL: {transformed_url}")
            return transformed_url
    
    logging.info("Not an arXiv URL, returning original")
    return url

def is_pdf_url(url: str) -> bool:
    """Check if URL is likely to be a PDF"""
    return url.lower().endswith('.pdf') or 'arxiv.org/pdf' in url.lower()

async def acquire_rate_limit():
    """Implement token bucket rate limiting"""
    now = time.time()
    
    # Remove timestamps older than our rate limit window
    global last_request_times
    last_request_times = [t for t in last_request_times if now - t < RATE_PERIOD]
    
    if len(last_request_times) >= RATE_LIMIT:
        # Wait until the oldest request expires
        sleep_time = RATE_PERIOD - (now - last_request_times[0])
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
            return await acquire_rate_limit()
    
    last_request_times.append(now)
    return True

app = FastAPI()
app.mount("/static", StaticFiles(directory="templates"), name="static")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logging.error(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid URL format. Please ensure the URL starts with http:// or https://"
        }
    )

@app.post("/cancel/{tracker_id}")
async def cancel_scrape(tracker_id: str):
    """Endpoint to cancel an ongoing scraping operation"""
    return await cancel_scraping(tracker_id)

# Global trackers
progress_tracker = defaultdict(lambda: {
    "total": 0,
    "task": None,  # Store the scraping task
    "cancelled": False,  # Track cancellation status
    "processed": 0,
    "successful": 0,
    "potential_successful": 0,  # Track potential successes during fetching
    "skipped": 0,
    "failed": 0,
    "current_url": ""
})
results_tracker = {}  # Store temporary results for download

class ScrapeRequest(BaseModel):
    url: AnyHttpUrl  # More lenient URL validation

class ScrapeResponse(BaseModel):
    links: list[str]
    jobId: str
    successful: int = 0
    skipped: int = 0
    failed: int = 0

async def get_markdown_content(url: str, client: httpx.AsyncClient, tracker_id: str) -> tuple[str, str]:
    """Get markdown content from Jina API with retries"""
    progress_tracker[tracker_id]["current_url"] = url
    
    if should_skip_url(url):
        progress_tracker[tracker_id]["processed"] += 1
        progress_tracker[tracker_id]["skipped"] += 1
        return url, ""  # Return empty string for skipped URLs
    
    # Transform arXiv URLs
    original_url = url
    transformed_url = transform_arxiv_url(url)
    if transformed_url != url:
        logging.info(f"URL transformation: {url} -> {transformed_url}")
    
    # Set timeout based on content type
    is_pdf = is_pdf_url(transformed_url)
    timeout = PDF_TIMEOUT if is_pdf else DEFAULT_TIMEOUT
    logging.info(f"Using timeout {timeout}s for {'PDF' if is_pdf else 'regular'} URL: {transformed_url}")
    
    start_time = time.time()
    retries = 0
    last_error = None
    
    while retries <= MAX_RETRIES:
        try:
            # Apply rate limiting
            await acquire_rate_limit()
            
            jina_url = f"https://r.jina.ai/{transformed_url}"
            logging.info(f"Fetching content from Jina: {jina_url}")
            
            response = await client.get(jina_url, timeout=timeout)
            
            if response.status_code == 200:
                content = response.text.strip()
                logging.info(f"Got response length: {len(content)} chars")
                
                # Check if content is too short, empty, or just contains the URL/title
                if len(content) < 50 or content.count('\n') < 3:
                    raise Exception("Retrieved content too short or empty")
                
                # Check if content only contains URL and title
                lines = content.split('\n')
                if all(line.startswith(('# Original URL:', 'Title:', 'URL Source:', 'Markdown Content:')) 
                       for line in lines if line.strip()):
                    raise Exception("Retrieved content contains only metadata")
                
                elapsed = time.time() - start_time
                logging.info(f"Successfully fetched {original_url} in {elapsed:.2f} seconds")
                progress_tracker[tracker_id]["processed"] += 1
                progress_tracker[tracker_id]["potential_successful"] += 1  # Increment potential successes
                return url, content
            
            if response.status_code == 429:  # Too Many Requests
                retries += 1
                if retries <= MAX_RETRIES:
                    wait_time = RETRY_DELAY * retries
                    logging.warning(f"Rate limit hit for {url}, waiting {wait_time} seconds")
                    await asyncio.sleep(wait_time)  # Exponential backoff
                    continue
            
            last_error = f"Failed to get content: {response.status_code}"
            raise Exception(last_error)
            
        except Exception as e:
            last_error = str(e)
            retries += 1
            if retries <= MAX_RETRIES:
                wait_time = RETRY_DELAY * retries
                if "429" in str(e) or "too short" in str(e) or "only metadata" in str(e):
                    logging.warning(f"Error for {url}, waiting {wait_time} seconds: {e}")
                    await asyncio.sleep(wait_time)
                    continue
            logging.error(f"Error getting markdown for {url}: {e}")
            break
    
    progress_tracker[tracker_id]["processed"] += 1
    progress_tracker[tracker_id]["failed"] += 1
    return url, ""  # Return empty string for failed URLs

async def progress_generator(tracker_id: str):
    """Generate SSE events for progress updates"""
    while progress_tracker[tracker_id]["processed"] < progress_tracker[tracker_id]["total"]:
        data = {
            "total": progress_tracker[tracker_id]["total"],
            "processed": progress_tracker[tracker_id]["processed"],
            "successful": progress_tracker[tracker_id]["potential_successful"],  # Show potential successes during progress
            "skipped": progress_tracker[tracker_id]["skipped"],
            "failed": progress_tracker[tracker_id]["failed"],
            "current_url": progress_tracker[tracker_id]["current_url"]
        }
        yield f"data: {json.dumps(data)}\n\n"
        await asyncio.sleep(0.5)
    
    # Send final update with confirmed successes
    data = {
        "total": progress_tracker[tracker_id]["total"],
        "processed": progress_tracker[tracker_id]["processed"],
        "successful": progress_tracker[tracker_id]["successful"],  # Use confirmed successes in final update
        "skipped": progress_tracker[tracker_id]["skipped"],
        "failed": progress_tracker[tracker_id]["failed"],
        "current_url": progress_tracker[tracker_id]["current_url"]
    }
    yield f"data: {json.dumps(data)}\n\n"

def create_zip_file(contents: list[tuple[str, str]], job_id: str, tracker_id: str) -> str:
    """Create a ZIP file with the scraped content"""
    temp_dir = Path(tempfile.gettempdir()) / job_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Reset success count before final validation
    progress_tracker[tracker_id]["successful"] = 0
    
    # Create individual markdown files only for non-empty content
    file_count = 0
    for url, content in contents:
        if not content:  # Skip empty content
            continue
            
        # Validate content again before writing
        lines = content.split('\n')
        if (len(content.strip()) < 50 or content.count('\n') < 3 or
            all(line.startswith(('# Original URL:', 'Title:', 'URL Source:', 'Markdown Content:')) 
                for line in lines if line.strip())):
            logging.info(f"Skipping invalid content for {url}")
            progress_tracker[tracker_id]["failed"] += 1  # Increment failed count
            continue
        
        # Extract title and create safe filename
        title = extract_title_from_content(content)
        safe_filename = create_safe_filename(title, url)
        logging.info(f"Creating file: {safe_filename} for URL: {url}")
        
        file_path = temp_dir / safe_filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# Original URL: {url}\n\n{content}")
        file_count += 1
        progress_tracker[tracker_id]["successful"] += 1  # Increment confirmed successes
    
    if file_count == 0:
        raise Exception("No valid content to download")
    
    # Create ZIP file
    zip_path = temp_dir.parent / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in temp_dir.glob('*.md'):
            zipf.write(file, file.name)
    
    # Clean up individual files
    shutil.rmtree(temp_dir)
    
    return str(zip_path)

@app.get("/", response_class=HTMLResponse)
async def read_root():
    html_path = Path("templates/index.html")
    return HTMLResponse(content=html_path.read_text())

@app.get("/api/scrape/progress")
async def scrape_progress(url: str):
    """SSE endpoint for progress updates"""
    tracker_id = hash(url)
    return StreamingResponse(
        progress_generator(str(tracker_id)),
        media_type="text/event-stream"
    )

@app.get("/api/download/{job_id}")
async def download_results(job_id: str):
    """Download endpoint for scraped content"""
    if job_id not in results_tracker:
        raise HTTPException(status_code=404, detail="Results not found")
    
    zip_path = results_tracker[job_id]
    
    async def cleanup():
        await asyncio.sleep(300)  # Clean up after 5 minutes
        try:
            Path(zip_path).unlink()
            del results_tracker[job_id]
        except:
            pass
    
    asyncio.create_task(cleanup())
    
    return FileResponse(
        zip_path,
        media_type='application/zip',
        filename=f'scraped-content-{job_id}.zip'
    )

@app.post("/api/scrape", response_model=ScrapeResponse)
async def start_scraping(request: ScrapeRequest):
    """Start a new scraping operation"""
    return await scrape_url(request)

async def scrape_url(request: ScrapeRequest):
    tracker_id = str(hash(str(request.url)))
    job_id = str(uuid4())
    
    async with httpx.AsyncClient(timeout=30.0) as client:  # Add timeout
        try:
            # First get markdown for the original URL
            original_content = await get_markdown_content(str(request.url), client, tracker_id)
            results = [original_content]
            
            # Then get the HTML to extract links
            response = await client.get(str(request.url))
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all links and filter unwanted ones
            links = [
                a['href'] for a in soup.find_all('a', href=True)
                if a['href'].startswith('http') and not should_skip_url(a['href'])
            ]
            
            # Initialize progress tracker (add 1 for original URL)
            progress_tracker[tracker_id]["total"] = len(links) + 1
            progress_tracker[tracker_id]["processed"] = 1  # Original URL already processed
            
            # Process links in smaller batches
            batch_size = 10  # Reduced batch size
            
            for i in range(0, len(links), batch_size):
                batch = links[i:i + batch_size]
                tasks = [
                    get_markdown_content(link, client, tracker_id)
                    for link in batch
                ]
                batch_results = await asyncio.gather(*tasks)
                results.extend(batch_results)
                
                # Wait longer between batches
                if i + batch_size < len(links):
                    await asyncio.sleep(RATE_PERIOD / 2)  # Wait 30 seconds between batches
            
            try:
                # Create ZIP file
                zip_path = create_zip_file(results, job_id, tracker_id)
                results_tracker[job_id] = zip_path
            except Exception as e:
                logging.error(f"Error creating ZIP file: {e}")
                # Even if ZIP creation fails, we'll return the counts
            
            # Get final counts
            final_counts = progress_tracker[tracker_id]
            
            # Clean up tracker
            del progress_tracker[tracker_id]
            
            return ScrapeResponse(
                links=[str(request.url)] + links,
                jobId=job_id,
                successful=final_counts["successful"],
                skipped=final_counts["skipped"],
                failed=final_counts["failed"]
            )
            
        except Exception as e:
            # Clean up tracker on error
            if tracker_id in progress_tracker:
                del progress_tracker[tracker_id]
            raise HTTPException(
                status_code=500,
                detail=f"Error scraping URL: {str(e)}"
            )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)