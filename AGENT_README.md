# AI Agent-Powered Scraping System

## Overview

This project now features a **hybrid architecture** that combines traditional scraping with AI agents powered by Claude Opus 4.5. This enables **prompt-native workflows** where users describe what they want in plain English, and the AI autonomously figures out how to accomplish it.

## What's New: Prompt-Native Architecture

### Traditional Scraping (Before)
```
User → Hardcoded Rules → Scrape → Download Files
```
- Fixed functionality
- User gets raw data
- Requires coding to change behavior

### Prompt-Native Scraping (After)
```
User → Natural Language Goal → AI Agent → Intelligent Research → Synthesized Insights
```
- Flexible, user-defined workflows
- User gets answers, not just data
- No coding required to create new features

## Architecture

### 1. Fast Extraction Service (`FastExtractor`)
- **Model**: Claude Haiku 4 (optimized for speed & cost)
- **Use Cases**:
  - Title extraction
  - Content classification
  - Quick summarization
- **Cost**: ~$0.005 per extraction

### 2. Research Agent (`ResearchAgent`)
- **Model**: Claude Opus 4.5 (advanced reasoning)
- **Capabilities**:
  - Multi-step autonomous workflows
  - Tool use (scraping, search, analysis)
  - Adaptive problem solving
- **Cost**: ~$0.50-$2.00 per research task

### 3. Smart Scraper (`SmartScraper`)
- Orchestrates both systems
- Routes tasks to optimal model
- Handles batch processing

## Features

### 🔬 Research Workflow
Describe your research goal in plain English. The agent autonomously:
- Identifies relevant sources
- Scrapes content
- Extracts key information
- Synthesizes findings

**Example:**
```json
{
  "goal": "Research sustainable fashion brands and compare their sustainability practices",
  "urls": ["https://patagonia.com", "https://allbirds.com"]
}
```

### ⚡ Quick Scrape
Fast scraping with AI-powered extraction using Claude Haiku.

**Example:**
```json
{
  "url": "https://example.com"
}
```

**Returns:**
```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "content": "...",
  "classification": {
    "content_type": "article",
    "quality": "high",
    "has_substance": true
  }
}
```

### 📊 Batch Analysis
Scrape multiple URLs and get intelligent synthesis.

**Example:**
```json
{
  "urls": ["https://company1.com", "https://company2.com"],
  "analysis_goal": "Compare their product offerings and pricing strategies"
}
```

## API Endpoints

### Agent-Powered Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent` | GET | Serve AI agent UI |
| `/api/agent/quick-scrape` | POST | Fast scraping with AI extraction |
| `/api/agent/research` | POST | Prompt-native research workflow |
| `/api/agent/batch-analyze` | POST | Batch scraping with synthesis |
| `/api/agent/examples` | GET | Get example workflows |

### Traditional Endpoints
All original endpoints (`/api/scrape`, etc.) remain unchanged.

## Setup

### Environment Variables
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

### Install Dependencies
```bash
uv sync
```

### Run Server
```bash
uv run uvicorn main:app --reload
```

### Access UIs
- **Classic Scraper**: http://localhost:8000/
- **AI Agent Mode**: http://localhost:8000/agent

## Usage Examples

### Example 1: Competitive Research
```bash
curl -X POST http://localhost:8000/api/agent/research \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Compare the pricing strategies of these e-commerce sites",
    "urls": ["https://amazon.com", "https://ebay.com"]
  }'
```

### Example 2: Academic Research
```bash
curl -X POST http://localhost:8000/api/agent/research \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Summarize the key findings from recent AI safety research",
    "urls": ["https://arxiv.org/abs/2301.12345"]
  }'
```

### Example 3: Quick Content Classification
```bash
curl -X POST http://localhost:8000/api/agent/quick-scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://news.ycombinator.com"
  }'
```

## How It Works

### Agentic Loop (Research Workflow)

1. **User provides goal**: "Research X and find Y"
2. **Agent plans approach**: Decides what tools to use
3. **Tool execution**: Agent calls tools (scrape, search, analyze)
4. **Iterative refinement**: Agent continues until goal is met
5. **Synthesis**: Agent creates final response

### Tool Use Example

The agent has access to these tools:
- `scrape_url`: Fetch content from any URL
- `web_search`: Search for information (placeholder - integrate real search)
- `extract_links`: Get all links from a page
- `analyze_content`: Deep analysis of content

The agent autonomously decides which tools to use and when.

## Cost Optimization

### Hybrid Strategy
- **Simple tasks** → Haiku (cheap & fast)
- **Complex reasoning** → Opus (powerful but expensive)

### Cost Comparison

**Scenario**: Scraping 100 pages with analysis

| Approach | Cost per Job |
|----------|-------------|
| All Opus | $50-100 |
| **Hybrid** | **$6.50-11.50** |

**Savings**: 5-8x cheaper

### Optimization Tips

1. Use `quick-scrape` for simple extraction
2. Use `research` workflow only when needed
3. Batch similar requests
4. Cache common extractions
5. Use `analysis_goal` to focus agent's work

## Development

### File Structure
```
.
├── main.py              # FastAPI app (original + new endpoints)
├── agent_system.py      # AI agent architecture
├── templates/
│   ├── index.html       # Classic scraper UI
│   └── agent.html       # AI agent UI
└── AGENT_README.md      # This file
```

### Extending the System

#### Add New Tools
```python
# In agent_system.py
def _define_tools(self):
    return [
        {
            "name": "your_tool",
            "description": "What it does",
            "input_schema": {...}
        }
    ]

async def _handle_your_tool(self, param: str) -> str:
    # Implementation
    return result
```

#### Create Custom Workflows
Users can create workflows via the UI or API:

```python
await scraper.research_workflow(
    goal="Your custom research goal here",
    urls=["starting", "urls"]
)
```

## Real-World Use Cases

### 1. Market Research
"Analyze competitor pricing across 20 e-commerce sites and identify market gaps"

### 2. Due Diligence
"Research this startup - find team info, funding history, and product offerings"

### 3. Academic Literature Review
"Summarize 50 papers on quantum computing and identify research trends"

### 4. Content Curation
"Scan 100 tech blogs and find the 10 most important AI news stories this week"

### 5. Compliance Monitoring
"Track privacy policy changes across 50 vendor websites and flag concerning clauses"

## Roadmap

- [ ] Add real web search integration (Google, Brave API)
- [ ] Implement workflow saving/sharing
- [ ] Add streaming responses for real-time feedback
- [ ] Create workflow marketplace
- [ ] Add user authentication
- [ ] Implement caching for common queries
- [ ] Add PDF/EPUB export formats
- [ ] Create custom agents per industry
- [ ] Add cancellation support for long-running jobs

## Performance

### Speed
- Quick scrape: 2-5 seconds
- Research workflow: 30-120 seconds
- Batch analysis: 1-5 minutes (depends on batch size)

### Reliability
- Automatic retries on errors
- Graceful degradation
- Detailed error logging

## Troubleshooting

### API Key Not Set
```bash
export ANTHROPIC_API_KEY="your-key"
```

### Slow Responses
- Research workflows use Opus (slower but smarter)
- Use quick-scrape for simple tasks
- Reduce batch sizes

### Tool Errors
Check logs for specific tool failures:
```bash
tail -f logs/agent.log
```

## Contributing

This is a proof-of-concept demonstrating prompt-native architecture. Contributions welcome!

### Areas for Contribution
1. Additional tool implementations
2. UI improvements
3. Cost optimization strategies
4. New workflow templates
5. Documentation improvements

## License

MIT

## Credits

Built with:
- [Anthropic Claude](https://anthropic.com) - AI models
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [Jina Reader](https://jina.ai/) - Content extraction
