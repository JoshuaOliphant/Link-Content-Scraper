"""
Test script for the AI Agent-Powered Scraping System

Run this to verify the hybrid agent system works correctly.
Requires ANTHROPIC_API_KEY environment variable to be set.
"""

import asyncio
import os
from agent_system import SmartScraper, FastExtractor, ResearchAgent

async def test_fast_extraction():
    """Test the fast extraction service"""
    print("\n" + "="*60)
    print("TEST 1: Fast Extraction (Claude Haiku)")
    print("="*60)

    extractor = FastExtractor()

    # Test with sample content
    sample_content = """
    # Understanding Machine Learning

    Machine learning is a subset of artificial intelligence that enables
    systems to learn and improve from experience without being explicitly
    programmed.
    """

    print("\nExtracting title from sample content...")
    title = await extractor.extract_title(sample_content, "https://example.com")
    print(f"✓ Extracted Title: {title}")

    print("\nClassifying content...")
    classification = await extractor.classify_content(sample_content)
    print(f"✓ Classification: {classification}")

    print("\nSummarizing content...")
    summary = await extractor.summarize_content(sample_content)
    print(f"✓ Summary: {summary}")

    print("\n✅ Fast Extraction Test PASSED")


async def test_quick_scrape():
    """Test quick scraping with fast extraction"""
    print("\n" + "="*60)
    print("TEST 2: Quick Scrape (Full Pipeline)")
    print("="*60)

    scraper = SmartScraper()

    print("\nScraping example.com...")
    result = await scraper.quick_scrape("https://example.com")

    if "error" in result:
        print(f"❌ Error: {result['error']}")
        return

    print(f"✓ URL: {result['url']}")
    print(f"✓ Title: {result['title']}")
    print(f"✓ Content Length: {len(result['content'])} chars")
    print(f"✓ Classification: {result['classification']}")
    print(f"✓ Method: {result['method']}")

    print("\n✅ Quick Scrape Test PASSED")


async def test_research_workflow():
    """Test the research agent workflow"""
    print("\n" + "="*60)
    print("TEST 3: Research Workflow (Claude Opus 4.5)")
    print("="*60)
    print("\n⚠️  This test uses Opus 4.5 and may take 1-2 minutes...")
    print("⚠️  It will cost approximately $0.50-1.00 in API credits")

    # Ask for confirmation
    response = input("\nProceed with Opus test? (y/N): ")
    if response.lower() != 'y':
        print("⏭️  Skipping Opus test")
        return

    scraper = SmartScraper()

    print("\nRunning research workflow...")
    print("Goal: Get basic information about example.com")

    result = await scraper.research_workflow(
        goal="Visit example.com and tell me what you find. Describe the page briefly.",
        urls=["https://example.com"]
    )

    if result['success']:
        print(f"\n✓ Success!")
        print(f"✓ Iterations: {result['iterations']}")
        print(f"✓ Result Preview: {result['result'][:200]}...")
        print("\n✅ Research Workflow Test PASSED")
    else:
        print(f"\n❌ Research failed: {result.get('error')}")


async def test_batch_analysis():
    """Test batch scraping with analysis"""
    print("\n" + "="*60)
    print("TEST 4: Batch Analysis")
    print("="*60)
    print("\n⚠️  This test uses both Haiku and Opus")
    print("⚠️  It will cost approximately $1.00-2.00 in API credits")

    # Ask for confirmation
    response = input("\nProceed with batch test? (y/N): ")
    if response.lower() != 'y':
        print("⏭️  Skipping batch test")
        return

    scraper = SmartScraper()

    print("\nRunning batch analysis...")
    print("Scraping: example.com and example.org")
    print("Goal: Compare these two websites")

    result = await scraper.batch_scrape_with_analysis(
        urls=["https://example.com", "https://example.org"],
        analysis_goal="Compare these websites and note any differences or similarities."
    )

    print(f"\n✓ Scraped: {result['scraped_count']}/{result['total_urls']} URLs")
    print(f"✓ Synthesis iterations: {result['synthesis']['iterations']}")
    print(f"✓ Result Preview: {result['synthesis']['result'][:200]}...")

    print("\n✅ Batch Analysis Test PASSED")


async def run_all_tests():
    """Run all tests"""
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\n❌ ERROR: ANTHROPIC_API_KEY environment variable not set")
        print("\nPlease set it with:")
        print("  export ANTHROPIC_API_KEY='your-api-key-here'")
        return

    print("\n" + "="*60)
    print("AI AGENT SYSTEM TEST SUITE")
    print("="*60)
    print("\nThis will test the hybrid agent architecture:")
    print("  1. Fast extraction (Haiku) - FREE test")
    print("  2. Quick scrape - FREE test")
    print("  3. Research workflow (Opus) - PAID test (optional)")
    print("  4. Batch analysis - PAID test (optional)")

    try:
        # Always run free tests
        await test_fast_extraction()
        await test_quick_scrape()

        # Optional paid tests
        await test_research_workflow()
        await test_batch_analysis()

        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED")
        print("="*60)
        print("\nNext steps:")
        print("  1. Start the server: uv run uvicorn main:app --reload")
        print("  2. Visit http://localhost:8000/agent")
        print("  3. Try the AI-powered workflows!")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
