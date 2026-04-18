"""
Hybrid Agent Architecture for Link Content Scraper

This module provides:
1. Agent SDK approach: Complex multi-step reasoning with tool use (Opus 4.5)
2. Direct API approach: Fast, simple extraction (Haiku/Sonnet)
3. Integration with existing scraper infrastructure
"""

from anthropic import Anthropic, AsyncAnthropic
from typing import List, Dict, Optional, Any, Callable
import os
import json
import logging
import asyncio
import ipaddress
import re
import socket
import time
import httpx
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scraping constants (mirrors main.py values)
MAX_RETRIES = 3
RETRY_DELAY = 5  # base delay in seconds
PDF_TIMEOUT = 60.0
DEFAULT_TIMEOUT = 30.0
BATCH_SIZE = 10
BATCH_DELAY = 1.0  # seconds between batches


def _transform_arxiv_url(url: str) -> str:
    """Transform arXiv abs/html URLs to their PDF equivalents."""
    patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)(v\d+)?',
        r'arxiv\.org/pdf/(\d+\.\d+)(v\d+)?\.pdf',
        r'arxiv\.org/html/(\d+\.\d+)(v\d+)?',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            paper_id = match.group(1)
            version = match.group(2) or ''
            return f"https://arxiv.org/pdf/{paper_id}{version}.pdf"
    return url


def _is_pdf_url(url: str) -> bool:
    return url.lower().endswith('.pdf') or 'arxiv.org/pdf' in url.lower()


def _validate_external_url(url: str) -> None:
    """
    Raise ValueError if url is not a safe external http/https URL.
    Blocks private, loopback, link-local, and reserved IP ranges (SSRF guard).
    """
    try:
        parsed = re.match(r'^(https?)://([^/:]+)', url, re.IGNORECASE)
        if not parsed:
            raise ValueError(f"URL must start with http:// or https://: {url}")
        scheme = parsed.group(1).lower()
        if scheme not in ('http', 'https'):
            raise ValueError(f"Disallowed scheme '{scheme}' in URL: {url}")
        hostname = parsed.group(2)
        # Resolve host to IP and check against private ranges
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        except socket.gaierror:
            raise ValueError(f"Cannot resolve hostname: {hostname}")
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(f"Requests to private/internal addresses are not allowed: {ip}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"URL validation error: {e}")


class FastExtractor:
    """
    Direct API approach for simple, high-volume operations.
    Uses Haiku for cost efficiency and speed.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    async def extract_title(self, content: str, url: str) -> str:
        """Extract title from content using fast Haiku model"""
        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": f"""Extract the main title from this content.

URL: {url}

Content:
{content[:1500]}

Return only the title, nothing else. If no clear title, return "Untitled"."""
                }]
            )
            title = response.content[0].text.strip()
            logger.info(f"Extracted title: {title[:50]}...")
            return title
        except Exception as e:
            logger.error(f"Error extracting title: {e}")
            return "Untitled"

    async def classify_content(self, content: str) -> Dict[str, Any]:
        """Classify content type and quality"""
        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": f"""Classify this content.

Content:
{content[:1000]}

Return JSON with:
- content_type: article, blog, documentation, academic, news, or other
- quality: high, medium, or low
- has_substance: true or false (is it more than just metadata?)

Return ONLY valid JSON, no other text."""
                }]
            )
            result = json.loads(response.content[0].text)
            return result
        except Exception as e:
            logger.error(f"Error classifying content: {e}")
            return {"content_type": "other", "quality": "medium", "has_substance": True}

    async def summarize_content(self, content: str, max_length: int = 200) -> str:
        """Quick summarization using Sonnet"""
        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_length,
                messages=[{
                    "role": "user",
                    "content": f"""Summarize this content in 2-3 sentences.

{content[:3000]}"""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error summarizing: {e}")
            return ""


class ResearchAgent:
    """
    Agent approach for complex, multi-step workflows.
    Uses Opus 4.6 with tool calling for autonomous reasoning.
    """

    def __init__(self, api_key: Optional[str] = None, rate_limiter: Optional[Callable] = None):
        self.client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.rate_limiter = rate_limiter
        self.tools = self._define_tools()
        self.tool_handlers = self._register_tool_handlers()

    def _define_tools(self) -> List[Dict]:
        """Define available tools for the agent"""
        return [
            {
                "name": "scrape_url",
                "description": "Scrape content from a URL and convert to markdown using Jina Reader API. Use this to fetch content from any webpage.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to scrape"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "web_search",
                "description": "Search the web for information. Use this to find relevant URLs or information on a topic.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "extract_links",
                "description": "Extract all links from scraped HTML content. Returns a list of URLs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to extract links from"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "analyze_content",
                "description": "Perform deep analysis on content (extract key points, entities, themes, etc.)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The content to analyze"
                        },
                        "analysis_type": {
                            "type": "string",
                            "description": "Type of analysis: 'key_points', 'entities', 'themes', or 'summary'"
                        }
                    },
                    "required": ["content", "analysis_type"]
                }
            }
        ]

    def _register_tool_handlers(self) -> Dict[str, Callable]:
        """Register handlers for each tool"""
        return {
            "scrape_url": self._handle_scrape_url,
            "web_search": self._handle_web_search,
            "extract_links": self._handle_extract_links,
            "analyze_content": self._handle_analyze_content
        }

    async def _handle_scrape_url(self, url: str) -> str:
        """Scrape URL using Jina Reader with rate limiting and retries."""
        url = _transform_arxiv_url(url)
        timeout = PDF_TIMEOUT if _is_pdf_url(url) else DEFAULT_TIMEOUT
        jina_url = f"https://r.jina.ai/{url}"
        last_error: Exception = Exception("Unknown error")
        for attempt in range(MAX_RETRIES + 1):
            try:
                if self.rate_limiter:
                    await self.rate_limiter()
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(jina_url)
                    if response.status_code == 200:
                        return response.text
                    last_error = Exception(f"Status {response.status_code}")
            except Exception as e:
                last_error = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
        return f"Error scraping {url}: {last_error}"

    async def _handle_web_search(self, query: str) -> str:
        """Simple web search simulation (in production, use real search API)"""
        # For now, return a placeholder
        # In production, integrate with Google Custom Search, Brave Search API, etc.
        return f"Search results for '{query}' would appear here. Integrate with a search API for real results."

    async def _handle_extract_links(self, url: str) -> str:
        """Extract links from a URL (SSRF-safe: only public http/https hosts)."""
        try:
            _validate_external_url(url)
        except ValueError as e:
            return f"Error: {e}"
        try:
            from bs4 import BeautifulSoup
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.get(url)
                soup = BeautifulSoup(response.text, 'html.parser')
                links = [a['href'] for a in soup.find_all('a', href=True)
                        if a['href'].startswith('http')]
                return json.dumps(links[:50])  # Return first 50 links
        except Exception as e:
            return f"Error extracting links: {str(e)}"

    async def _handle_analyze_content(self, content: str, analysis_type: str) -> str:
        """Analyze content using Sonnet"""
        prompts = {
            "key_points": "Extract the 5 most important points from this content.",
            "entities": "Extract all important entities (people, organizations, locations, concepts).",
            "themes": "Identify the main themes and topics discussed.",
            "summary": "Provide a comprehensive summary."
        }

        prompt = prompts.get(analysis_type, prompts["summary"])

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": f"{prompt}\n\nContent:\n{content[:5000]}"
                }]
            )
            return response.content[0].text
        except Exception as e:
            return f"Error analyzing content: {str(e)}"

    async def execute_workflow(self, user_goal: str, starting_urls: List[str] = None) -> Dict[str, Any]:
        """
        Execute a prompt-native workflow.
        The agent autonomously decides what tools to use and how to accomplish the goal.
        """
        logger.info(f"Starting workflow: {user_goal}")

        # Build the initial prompt
        initial_message = f"""You are a research assistant helping with web scraping and content analysis.

User's Goal: {user_goal}

{f"Starting URLs: {', '.join(starting_urls)}" if starting_urls else ""}

Plan your approach, use the available tools, and accomplish the user's goal.
When you're done, provide a final summary of what you found and accomplished.

Think step-by-step about what information you need and what tools to use."""

        messages = [{"role": "user", "content": initial_message}]

        # Agentic loop with tool calling
        max_iterations = 10
        iteration = 0
        final_response = None

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"Agent iteration {iteration}/{max_iterations}")

            try:
                response = await self.client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=4096,
                    tools=self.tools,
                    messages=messages
                )

                # Check if we're done (no tool calls)
                if response.stop_reason == "end_turn":
                    final_response = response.content
                    break

                # Process tool calls
                if response.stop_reason == "tool_use":
                    # Add assistant message to conversation
                    messages.append({"role": "assistant", "content": response.content})

                    # Execute each tool call
                    tool_results = []
                    for content_block in response.content:
                        if content_block.type == "tool_use":
                            tool_name = content_block.name
                            tool_input = content_block.input
                            tool_id = content_block.id

                            logger.info(f"Executing tool: {tool_name} with input: {tool_input}")

                            # Execute the tool
                            handler = self.tool_handlers.get(tool_name)
                            if handler:
                                result = await handler(**tool_input)
                            else:
                                result = f"Tool {tool_name} not implemented"

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": str(result)
                            })

                    # Add tool results to conversation
                    messages.append({"role": "user", "content": tool_results})
                else:
                    # Unexpected stop reason
                    logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                    final_response = response.content
                    break

            except Exception as e:
                logger.error(f"Error in agent loop: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "iterations": iteration
                }

        # Extract final text response
        final_text = ""
        if final_response:
            for block in final_response:
                if hasattr(block, 'text'):
                    final_text += block.text

        return {
            "success": True,
            "result": final_text,
            "iterations": iteration,
        }


class SmartScraper:
    """
    Hybrid scraping system that combines:
    - Fast extraction for simple tasks
    - Agent-based workflows for complex research
    """

    def __init__(self, api_key: Optional[str] = None, rate_limiter: Optional[Callable] = None):
        self.rate_limiter = rate_limiter
        self.extractor = FastExtractor(api_key)
        self.agent = ResearchAgent(api_key, rate_limiter=rate_limiter)

    async def quick_scrape(self, url: str) -> Dict[str, Any]:
        """Quick scraping with fast extraction (optimized path)."""
        url = _transform_arxiv_url(url)
        timeout = PDF_TIMEOUT if _is_pdf_url(url) else DEFAULT_TIMEOUT
        jina_url = f"https://r.jina.ai/{url}"

        content = ""
        last_error: Exception = Exception("Unknown error")
        for attempt in range(MAX_RETRIES + 1):
            try:
                if self.rate_limiter:
                    await self.rate_limiter()
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(jina_url)
                    if response.status_code == 200:
                        content = response.text
                        break
                    last_error = Exception(f"Status {response.status_code}")
            except Exception as e:
                last_error = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
        else:
            logger.error(f"Error in quick_scrape: {last_error}")
            return {"url": url, "error": str(last_error)}

        if not content or not content.strip():
            return {"url": url, "error": "Empty response from scraper"}

        # Fast extraction using Haiku
        title = await self.extractor.extract_title(content, url)
        classification = await self.extractor.classify_content(content)

        if not classification.get("has_substance", True):
            return {"url": url, "error": "Content appears to be metadata-only or low-value"}

        return {
            "url": url,
            "title": title,
            "content": content,
            "classification": classification,
            "method": "fast_extraction"
        }

    async def research_workflow(self, goal: str, urls: List[str] = None) -> Dict[str, Any]:
        """
        Prompt-native research workflow.
        User describes what they want, agent figures out how to do it.
        """
        return await self.agent.execute_workflow(goal, urls)

    async def batch_scrape_with_analysis(self, urls: List[str], analysis_goal: str) -> Dict[str, Any]:
        """
        Scrape multiple URLs in batches of BATCH_SIZE with delays between batches,
        then synthesize results with the agent.
        """
        logger.info(f"Batch scraping {len(urls)} URLs with goal: {analysis_goal}")

        # Process URLs in fixed batches with delays (load control)
        all_results = []
        for batch_start in range(0, len(urls), BATCH_SIZE):
            batch = urls[batch_start:batch_start + BATCH_SIZE]
            batch_tasks = [self.quick_scrape(url) for url in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            all_results.extend(batch_results)
            if batch_start + BATCH_SIZE < len(urls):
                await asyncio.sleep(BATCH_DELAY)

        # Filter successful scrapes
        valid_results = [r for r in all_results if isinstance(r, dict) and "content" in r]

        # Build combined content and pass it into the synthesis prompt
        combined_content = "\n\n---\n\n".join([
            f"URL: {r['url']}\nTitle: {r.get('title', 'Untitled')}\n\n{r['content'][:1000]}"
            for r in valid_results
        ])

        synthesis_prompt = (
            f"{analysis_goal}\n\n"
            f"Analyze and synthesize the following scraped content:\n\n{combined_content}"
        )

        synthesis_result = await self.agent.execute_workflow(synthesis_prompt, [])

        return {
            "scraped_count": len(valid_results),
            "total_urls": len(urls),
            "individual_results": valid_results,
            "synthesis": synthesis_result
        }


# Example usage and testing
async def test_hybrid_system():
    """Test the hybrid agent system"""

    # Initialize
    scraper = SmartScraper()

    print("\n=== Test 1: Fast Extraction ===")
    result = await scraper.quick_scrape("https://anthropic.com")
    print(f"Title: {result.get('title')}")
    print(f"Classification: {result.get('classification')}")

    print("\n=== Test 2: Research Workflow ===")
    result = await scraper.research_workflow(
        "Research Anthropic's latest AI models. Find information about their capabilities and release dates.",
        ["https://anthropic.com"]
    )
    print(f"Result: {result.get('result', '')[:500]}...")
    print(f"Iterations: {result.get('iterations')}")

    print("\n=== Test 3: Batch Scrape with Analysis ===")
    result = await scraper.batch_scrape_with_analysis(
        ["https://anthropic.com", "https://openai.com"],
        "Compare these companies' approaches to AI safety"
    )
    print(f"Scraped: {result.get('scraped_count')}/{result.get('total_urls')}")
    print(f"Synthesis: {result.get('synthesis', {}).get('result', '')[:500]}...")


if __name__ == "__main__":
    asyncio.run(test_hybrid_system())
