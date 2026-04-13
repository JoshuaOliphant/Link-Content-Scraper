# Test Coverage: Unit Tests + BDD Scenarios

## Overview

Two beads issues drive this work:

- **`link_content_scraper-c5q`** — Unit tests for ProgressTracker, RateLimiter, and scraper module
- **`link_content_scraper-0bt`** — BDD scenarios replacing the originally planned e2e tests

## Decisions

- **No mocks.** Tests use real async primitives, real HTTP transports, and a local test server.
- **Dependency injection for standalone classes.** ProgressTracker and RateLimiter are instantiated fresh per test — no singletons.
- **Monkeypatch for scraper functions.** `get_markdown_content` and `scrape_site` use module-level singletons; we swap them via `monkeypatch.setattr` rather than changing the production API.
- **Local test HTTP server for BDD.** A real `asyncio` HTTP server serves controlled HTML/markdown responses. Not a mock — a real server on localhost.
- **pytest-bdd for Gherkin scenarios.** Feature files in `tests/features/`, step definitions alongside test files.

## New Dependencies

- `pytest-bdd` added to `[project.optional-dependencies] dev`

## File Layout

```
tests/
  conftest.py              # Local test HTTP server fixture, shared fixtures
  features/
    scraping.feature       # Gherkin scenarios for scrape lifecycle
  test_progress.py         # ProgressTracker unit tests
  test_rate_limit.py       # RateLimiter unit tests
  test_scraper.py          # Scraper module unit tests (get_markdown_content, create_zip_file edges)
  test_bdd_scrape.py       # BDD step definitions wired to scraping.feature
  test_content.py          # (existing)
  test_filters.py          # (existing)
  test_integration.py      # (existing)
  test_routes.py           # (existing)
```

## Unit Tests — ProgressTracker (`test_progress.py`)

Fresh `ProgressTracker()` per test. All async.

| Scenario | What it verifies |
|---|---|
| init sets total and processed | `init("id", total=10)` → `get` returns `total=10` |
| increment adds deltas | `increment("id", processed=1, successful=1)` adds to counters |
| increment ignores non-integer fields | `increment("id", current_url=1)` is a no-op on string field |
| update sets fields | `update("id", current_url="http://x")` sets the value |
| update ignores unknown keys | `update("id", bogus="x")` doesn't raise or create key |
| cancel marks cancelled | `cancel("id")` → `is_cancelled("id")` returns True |
| cancel cancels registered tasks | Register asyncio tasks, cancel tracker, verify tasks are cancelled |
| cancel returns False for unknown ID | `cancel("nope")` returns False |
| get returns snapshot not reference | Mutating returned dict doesn't affect internal state |
| get returns None for unknown ID | `get("nope")` returns None |
| exists / remove lifecycle | `init` → `exists` True → `remove` → `exists` False |
| generate_events yields SSE JSON | Init tracker, set progress, consume events, verify JSON structure |
| generate_events terminates on completion | Set processed == total, verify generator ends |
| generate_events terminates on cancel | Cancel mid-stream, verify cancelled event emitted |
| generate_events times out on missing tracker | Never init, verify timeout error event after wait |

## Unit Tests — RateLimiter (`test_rate_limit.py`)

Fresh `RateLimiter(limit=N, period=P)` per test with small values (e.g., `limit=3, period=1`). All async.

| Scenario | What it verifies |
|---|---|
| Acquires up to limit without blocking | 3 acquires complete instantly (< 0.1s total) |
| Blocks after limit exhausted | 4th acquire takes measurable time (≥ period) |
| Window expiry resets capacity | Exhaust limit, sleep past period, acquire succeeds immediately |
| Concurrent acquires respect limit | `asyncio.gather` N acquires, verify timing shows rate limiting |

## Unit Tests — Scraper Module (`test_scraper.py`)

### `create_zip_file`

Existing integration tests cover the happy path. Add:

| Scenario | What it verifies |
|---|---|
| Duplicate titles get unique filenames | Two URLs producing same title → ZIP has 2 distinct files |
| Content with no extractable title | Falls back to URL-based filename |
| Large content is included | Content over 10KB is written correctly |

### `get_markdown_content`

Uses `monkeypatch.setattr` on `scraper.progress_tracker` and `scraper.rate_limiter`. Uses an httpx `MockTransport` (a real transport callable, not a mock framework) for controlled HTTP responses.

| Scenario | What it verifies |
|---|---|
| Successful fetch returns content | 200 response with valid content → returns (url, content) |
| Skipped URL returns empty | URL matching skip list → returns (url, "") with skipped incremented |
| 429 triggers retry | First call 429, second call 200 → returns content |
| Content validation failure retries | Short content → retries, then fails |
| Cancelled mid-fetch returns empty | Set tracker cancelled before fetch → returns (url, "") |
| Network error retries then fails | Transport raises `httpx.ConnectError` → retries, then empty |

## BDD Scenarios (`tests/features/scraping.feature`)

### Test Infrastructure

`conftest.py` provides a local HTTP server fixture:
- Runs on `localhost` with a random available port
- Serves an index page with `<a href>` links to sub-pages
- Sub-pages return real HTML content
- The scraper's Jina URL prefix (`https://r.jina.ai/`) is monkeypatched to point at `http://localhost:{port}/` so `get_markdown_content` hits our local server. The local server returns markdown-like content directly (simulating what Jina would return).
- Configurable per-path: can return errors (4xx, 5xx), empty/minimal content, or slow responses via route configuration

### Scenarios

```gherkin
Feature: Web scraping lifecycle
  As a user of the link content scraper
  I want to scrape web pages and download them as markdown
  So that I can read web content offline

  Scenario: Successfully scrape a page and download results
    Given a target site with 3 linked pages
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    Then I receive a job ID and link list
    And I can download a ZIP file containing 4 markdown files
    And each markdown file contains the original URL header

  Scenario: Cancel an in-progress scrape
    Given a target site with 10 linked pages
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    And I cancel the scrape before it completes
    Then the cancellation is confirmed
    And the progress shows the scrape was cancelled

  Scenario: Scrape a non-existent URL
    Given the scraper is configured to use the local test server
    When I submit a scrape request for a URL that returns 404
    Then I receive a 502 error with a descriptive message

  Scenario: Upstream server error
    Given a target site that returns 500 for all pages
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    Then I receive an error indicating the scrape failed

  Scenario: All pages return empty content
    Given a target site where all pages have minimal content
    And the scraper is configured to use the local test server
    When I submit a scrape request for the target site
    Then I receive an error about no valid content
```

## Permissions Update (`.claude/settings.local.json`)

Clean up one-off inline commands and add blanket dev permissions for remote agent sessions:

```json
{
  "permissions": {
    "allow": [
      "Bash(uv:*)",
      "Bash(git:*)",
      "Bash(bd:*)",
      "Bash(gh:*)",
      "Bash(timeout:*)",
      "WebFetch(domain:docs.astral.sh)",
      "WebFetch(domain:fly.io)"
    ],
    "deny": []
  }
}
```

## Out of Scope

- Performance benchmarking of rate limiter
- Load testing with many concurrent jobs
- Testing the web UI (`templates/index.html`)
- SSE client-side integration testing
