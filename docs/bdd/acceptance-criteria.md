# Acceptance Criteria — pagefetch.com

Generated 2026-04-19. Four personas: Anonymous Visitor, Developer/API, Paying Subscriber, Web UI User.

---

## Acceptance Criteria: Anonymous Visitor — pagefetch.com

### AC-1: Visitor understands the product within 5 seconds of landing
**Given** an anonymous visitor arrives at `/` for the first time
**When** the page finishes loading
**Then** the hero section displays a headline that communicates the core action (fetch a URL, get linked pages as markdown)
  and a brief subheadline or description is visible without scrolling that explains the output format (ZIP of markdown files)
  and the "LINK SCRAPER" branding is visible as the primary identifier

**Edge cases:**
- Visitor arrives on a mobile viewport — all above-the-fold content remains readable without horizontal scroll

**Notes:** A one-sentence descriptor ("Paste a URL. Get every linked page as markdown.") should be present above the input field.

---

### AC-2: Visitor can identify the scraper input without guidance
**Given** an anonymous visitor is on `/`
**When** they view the page without interacting with anything
**Then** a URL input field is visible and labeled or placeholder-hinted clearly (e.g. `https://...`)
  and a primary CTA button is visually distinct and adjacent to the input
  and no login prompt is shown before the visitor attempts to use the tool

---

### AC-3: Visitor can locate pricing information from the homepage
**Given** an anonymous visitor is on `/`
**When** they scan the page for pricing or plan information
**Then** a navigation link or prominently placed CTA directing them to `/billing` is visible without scrolling
  and the link label clearly implies pricing (e.g. "Pricing", "Plans", "See Plans")

**Notes:** Billing UI does not yet exist. This is a blocker until `/billing` is rendered.

---

### AC-4: Visitor receives a clear auth error when submitting a URL without an API key
**Given** an anonymous visitor is on `/`
**When** they enter a valid URL into the scraper input and submit the form
**Then** the UI displays an error message indicating that an API key is required
  and the error message is visible inline (not hidden in a console or network tab)
  and the error message does not expose internal server details

**Edge cases:**
- Visitor submits an empty field — client-side validation fires before the API call ("Please enter a URL")
- Visitor submits a malformed URL — validation fires before auth is checked

**Notes:** Confirm `POST /api/scrape` returns HTTP 401 (not 403 or 500) when no API key header is present.

---

### AC-5: Unauthenticated error state includes a direct path to sign up
**Given** an anonymous visitor has submitted a URL and received the "API key required" error
**When** the error message is displayed
**Then** the error state includes a link or button for sign-up or plan selection (e.g. "Get an API key", "View Plans")
  and clicking that link navigates the visitor to `/billing`
  and the visitor's entered URL is NOT cleared from the input field

---

### AC-6: No partial scrape results are returned to an unauthenticated visitor
**Given** an anonymous visitor submits a URL without an API key
**When** the server processes the request
**Then** zero scraped content is returned to the client
  and no ZIP file download is initiated
  and no SSE progress stream is opened

**Notes:** Security boundary — confirm at the API layer, not just the UI layer.

---

### AC-7: Visitor can view all three pricing tiers on `/billing`
**Given** an anonymous visitor navigates to `/billing`
**When** the page loads
**Then** three plan cards are displayed: Starter ($9.99/mo, 5,000 URLs), Pro ($29.99/mo, 25,000 URLs), and Business ($99.99/mo, 150,000 URLs)
  and each card shows the plan name, monthly price, and URL quota
  and each card has a distinct CTA button

**Notes:** [BUILD REQUIRED] Billing UI does not exist on the frontend yet.

---

### AC-8: Visitor understands what distinguishes the tiers
**Given** an anonymous visitor is on `/billing`
**When** they read the plan cards
**Then** the primary differentiator (URL quota) is the most visually prominent piece of information after price
  and no plan card is missing a quota number
  and the billing cadence ("/mo") is shown on every plan

**Edge cases:**
- Visitor views on a narrow mobile viewport — all three plan cards are readable (stacked vertically acceptable)

---

### AC-9: Visitor can navigate back to the homepage from `/billing`
**Given** an anonymous visitor is on `/billing`
**When** they click the site logo or a "Back" / "Home" link
**Then** they are returned to `/`
  and their browser history contains `/billing` as a back-navigable entry

---

### AC-10: Clicking a plan CTA initiates checkout
**Given** an anonymous visitor is on `/billing` and has not authenticated
**When** they click the CTA on any plan card
**Then** they are directed to a checkout flow for that specific plan
  and the plan name and price are confirmed in the checkout UI
  and the visitor is not required to create an account before seeing the checkout form

---

### AC-11: Successful payment redirects to `/billing/success`
**Given** a visitor has completed checkout for any plan
**When** payment is confirmed
**Then** the visitor is redirected to `/billing/success`
  and the page loads without requiring a separate login step

**Edge cases:**
- Visitor navigates directly to `/billing/success` without completing payment — they see "No active session found" and are NOT shown an API key
- Visitor hits the browser back button from `/billing/success` — they are not shown a duplicate API key

---

### AC-12: API key is shown exactly once on `/billing/success`
**Given** a visitor has been redirected to `/billing/success` after successful payment
**When** the page loads
**Then** their API key is displayed in full, in a copyable text field or code block
  and a copy-to-clipboard button is present adjacent to the key
  and a visible warning states that the key will not be shown again
  and the page does not auto-redirect away before the visitor has had time to copy the key

**Edge cases:**
- Visitor refreshes `/billing/success` — the API key is NOT shown again
- Visitor has JavaScript disabled — the key is still rendered in the HTML (not JS-injected after page load)

---

### AC-13: Visitor receives the API key via email as a fallback
**Given** a visitor has completed checkout
**When** payment is confirmed
**Then** a confirmation email is sent to the address used at checkout containing the API key
  and the email contains a link to `/` with instructions on how to use the key

**Notes:** [BUILD REQUIRED] Email sending is not yet implemented. Requires transactional email service.

---

### AC-14: Visitor can use the API key immediately after receiving it
**Given** a visitor has their API key from `/billing/success`
**When** they navigate to `/` and submit a URL with the API key supplied
**Then** the scrape begins without an auth error
  and the progress UI updates as URLs are processed
  and a ZIP download is available upon completion

**Edge cases:**
- Visitor uses the API key before the Stripe webhook has been processed — error should say "Key not yet active, please wait a moment and retry" rather than "Invalid key"

**Notes:** [BUILD REQUIRED] No API key input field exists in the current UI.

---

### AC-15: Anonymous visitor is never shown another visitor's data
**Given** any state of the anonymous visitor flow
**When** any page or API response is rendered
**Then** no data belonging to another user's scrape job, API key, or account is returned
  and no scrape job IDs from other sessions are guessable via sequential integers

---

### AC-16: Visitor is not shown a broken or empty billing page
**Given** the billing UI does not yet exist on the frontend
**When** a visitor navigates to `/billing`
**Then** they do NOT see a raw 404 error, a blank white page, or an unhandled exception page
  and they see either a "coming soon" placeholder or a fully rendered billing page

---

## Acceptance Criteria: Developer / First API Call — pagefetch.com

### AC-1: Developer submits a valid URL and receives a job ID with discovered links
**Given** the developer has a valid API key included in the `X-API-Key` request header
  and the request body contains a well-formed URL (`{"url": "https://example.com"}`)
**When** the developer sends `POST /api/scrape`
**Then** the response status is `200 OK`
  and the response body contains a `jobId` string field
  and the response body contains a `links` array of discovered URLs

**Edge cases:**
- Site with a single page returns `links: []` (empty array, not null or absent)
- Redirect chains (301/302) are followed and the final URL is scraped

**Notes:** Define whether `links` represents all discovered URLs before scraping or only already-scraped ones.

---

### AC-2: Developer polls the download endpoint and receives a ZIP of markdown files
**Given** a `jobId` was returned from `POST /api/scrape`
  and the scrape job has completed
**When** the developer sends `GET /api/download/{jobId}`
**Then** the response status is `200 OK`
  and the `Content-Type` header is `application/zip`
  and each entry in the ZIP is a `.md` file
  and no `.md` file is empty (zero-byte files indicate a processing failure)

**Edge cases:**
- Job still in progress: returns `202 Accepted` with a status body, not a ZIP
- Unknown `jobId`: returns `404 Not Found`
- Expired `jobId` (past cleanup window): returns `404 Not Found` with a clear error message

---

### AC-3: Request with no API key is rejected
**Given** no `X-API-Key` header is present in the request
**When** the developer sends `POST /api/scrape`
**Then** the response status is `401 Unauthorized`
  and the response body contains a human-readable message indicating the API key is missing
  and no scrape job is created

**Edge cases:**
- Header present but value is empty string — also `401`
- Header name with wrong casing (e.g., `x-api-key`) — must still be accepted (HTTP headers are case-insensitive per RFC 7230)

---

### AC-4: Request with an invalid or revoked API key is rejected
**Given** the `X-API-Key` header is present
  and the value does not correspond to any active API key in the system
**When** the developer sends `POST /api/scrape`
**Then** the response status is `401 Unauthorized`
  and no scrape job is created

**Edge cases:**
- Revoked key: same `401` response — do not distinguish revoked from never-valid to avoid key enumeration
- Key belonging to suspended account: `401` with distinct code to aid support triage

---

### AC-5: Developer exceeds their monthly URL quota and receives a clear 429
**Given** the developer's account has consumed all URLs in their monthly tier allowance
**When** the developer sends `POST /api/scrape`
**Then** the response status is `429 Too Many Requests`
  and the response body contains a human-readable message naming the limit and the current tier
  and the response body contains a `limit` field (integer)
  and the response body contains a `used` field (integer)
  and the response body contains a `resetsAt` field (ISO 8601 timestamp)
  and the `Retry-After` HTTP header is set to seconds until quota reset
  and no scrape job is created

**Edge cases:**
- Job submitted that would partially exceed the limit — define whether the job is rejected upfront or runs until quota is hit mid-job

**Notes:** Partial-job behavior on quota hit is a product decision that must be made before this AC is fully testable.

---

### AC-6: Developer connects to the SSE stream and receives real-time progress events
**Given** a scrape job has been initiated
**When** the developer opens `GET /api/scrape/progress?url={url}`
**Then** the response status is `200 OK`
  and the `Content-Type` header is `text/event-stream`
  and each event payload contains at minimum: `{ "scraped": N, "total": N, "status": "..." }`
  and a terminal event is emitted when the job completes containing the `jobId` for download
  and the connection closes cleanly after the terminal event

**Edge cases:**
- Developer connects after job completion: stream immediately emits a single terminal event, then closes
- Network drop mid-stream: document whether `Last-Event-ID` replay is supported (V2 if not)

---

### AC-7: SSE stream with unknown URL parameter returns 404
**Given** the `url` query parameter does not correspond to any active or recent job
**When** the developer opens `GET /api/scrape/progress?url={url}`
**Then** the response status is `404 Not Found`
  and no SSE stream is opened

**Edge cases:**
- `url` parameter is missing entirely: `422 Unprocessable Entity`

---

### AC-8: Developer cancels an in-progress scrape
**Given** a scrape job is actively running
**When** the developer sends `POST /cancel/{tracker_id}`
**Then** the response status is `200 OK`
  and the response body confirms cancellation (e.g., `{ "status": "cancelled" }`)
  and no further pages are fetched after cancellation is acknowledged
  and the SSE stream emits a `cancelled` terminal event and closes

**Edge cases:**
- Cancelling an already-completed job: returns `409 Conflict`
- Cancelling an already-cancelled job: returns `409 Conflict`
- Unknown `tracker_id`: returns `404 Not Found`

**Notes:** `tracker_id` vs `jobId` naming inconsistency across endpoints should be resolved — developers will trip on this.

---

### AC-9: Developer submits a malformed URL and receives a validation error
**Given** the developer has a valid API key
**When** they send `POST /api/scrape` with a body where `url` is not a valid URL
**Then** the response status is `422 Unprocessable Entity`
  and the response body contains an `errors` array identifying the invalid field
  and no scrape job is created

**Edge cases:**
- URL with unsupported scheme (e.g., `ftp://`, `file://`): `422`
- URL resolving to a private/loopback address (SSRF vector): `422` or `403` — must be enforced server-side

**Notes:** SSRF prevention is a security requirement, not just a UX concern. Flag for security review.

---

### AC-10: Target site returns a 5xx error during scraping
**Given** a valid scrape job has started
  and the target site returns 5xx for one or more pages
**When** the scraper attempts to fetch those pages
**Then** the failed pages are retried up to `SCRAPER_MAX_RETRIES` times with `SCRAPER_RETRY_DELAY` backoff
  and if all retries are exhausted, the page is skipped and recorded as failed
  and the ZIP is still produced for all successfully scraped pages

---

### AC-11: Scraped content passes no valid content check
**Given** a valid scrape job has started
  and the scraper fetches a page (HTTP 200)
  and the page body yields no usable markdown content after extraction
**When** the content validation check runs
**Then** that page is excluded from the ZIP
  and it is included in a `skippedUrls` array with `reason: "NO_VALID_CONTENT"`
  and the overall job does not fail — other pages with valid content are still included

---

### AC-12: All error responses follow a consistent machine-readable structure
**Given** any error condition (401, 404, 409, 422, 429, 500)
**When** the API returns an error response
**Then** the `Content-Type` is `application/json`
  and the body always contains an `error` string (human-readable)
  and the body always contains a `statusCode` integer matching the HTTP status

**Edge cases:**
- Unhandled 500 errors: must still return JSON, not an HTML stack trace

---

## Acceptance Criteria: Paying Subscriber — pagefetch.com

### AC-1: Subscriber can view their current plan tier
**Given** a subscriber has a valid, active API key and is authenticated on the billing dashboard
**When** they navigate to the billing overview page
**Then** their current plan name (Starter, Pro, or Business) is displayed
  and the monthly price is shown
  and the plan's URL quota is displayed

**Notes:** [BUILD REQUIRED] Billing UI and a `GET /billing/status` endpoint both need to be built.

---

### AC-2: Subscriber can view their current usage for the billing period
**Given** a subscriber is on the billing overview page
**When** the page loads
**Then** the number of URLs scraped in the current billing period is displayed
  and the remaining quota is shown
  and the current billing period start and renewal date are shown

**Edge cases:**
- If usage data is unavailable, show "Usage data temporarily unavailable" rather than blank

---

### AC-3: Subscriber can access the Stripe Customer Portal via API
**Given** a subscriber has a valid, active API key
**When** they make a `GET /billing/portal` request with their `X-API-Key` header
**Then** the response contains a valid Stripe Customer Portal URL

**Edge cases:**
- Invalid or deactivated key: `401 Unauthorized`
- Stripe customer record missing: `404` or `500` with clear error

---

### AC-4: Subscriber can access the customer portal from the billing UI
**Given** a subscriber is on the billing overview page
**When** they click "Manage Subscription"
**Then** the frontend calls `GET /billing/portal` with the subscriber's API key
  and redirects the subscriber to the returned Stripe Customer Portal URL

**Notes:** [BUILD REQUIRED] Button and redirect flow do not yet exist on the frontend.

---

### AC-5: Subscriber can upgrade their plan via the Stripe Customer Portal
**Given** a subscriber is in the Stripe Customer Portal on the Starter plan
**When** they select the Pro or Business plan and confirm the upgrade
**Then** Stripe fires a `customer.subscription.updated` webhook
  and the subscriber's plan tier in the database is updated to the new tier
  and the subscriber's URL quota is immediately updated
  and the subscriber's existing API key remains valid and active

---

### AC-6: Subscriber can downgrade their plan via the Stripe Customer Portal
**Given** a subscriber is in the Stripe Customer Portal on a higher-tier plan
**When** they select a lower-tier plan and confirm the downgrade
**Then** the plan tier is updated at the next billing cycle
  and the subscriber's API key remains active

**Notes:** Policy decision needed: what happens if current-period usage exceeds the new lower tier's limit.

---

### AC-7: Subscriber can cancel their subscription via the Stripe Customer Portal
**Given** a subscriber has an active paid subscription
**When** they cancel their subscription and confirm
**Then** Stripe fires a `customer.subscription.deleted` webhook
  and the subscriber's plan is downgraded to the "free" tier
  and all API keys associated with the account are deactivated

**Edge cases:**
- `cancel_at_period_end` mode: key remains active until period ends, then deactivated

---

### AC-8: Cancelled subscriber sees a graceful message when their key is deactivated
**Given** a subscriber's subscription has been cancelled and their API key deactivated
**When** they make any API request using their deactivated key
**Then** the API returns `401 Unauthorized`
  and the response body contains a human-readable message explaining the key is inactive
  and the message includes instructions for reactivating

---

### AC-9: API keys are deactivated when a payment fails
**Given** a subscriber's payment method fails
**When** Stripe fires an `invoice.payment_failed` webhook
**Then** the subscriber's API keys are deactivated
  and subsequent API requests with those keys return `401` with an explanatory message

**Edge cases:**
- If the payment eventually succeeds (retry), `invoice.payment_succeeded` must reactivate the key automatically

**Notes:** [VERIFY] `invoice.payment_succeeded` handler must exist to restore access — if not implemented, this is a critical gap.

---

### AC-10: Subscriber is notified by email when their payment fails
**Given** a subscriber's payment fails
**When** Stripe fires the `invoice.payment_failed` webhook
**Then** the subscriber receives an email informing them of the failure
  and the email includes a link to update their payment method via Stripe Portal
  and the email is sent within 5 minutes of webhook receipt

**Notes:** [BUILD REQUIRED] Email sending is not yet implemented. Critical trust gap for paid subscribers.

---

### AC-11: Subscriber is clearly informed the API key cannot be retrieved after initial display
**Given** a subscriber has just completed checkout on `/billing/success`
**When** the page displays their API key
**Then** a prominent warning states the key will not be displayed again
  and a copy-to-clipboard affordance is provided

**Edge cases:**
- Page refresh: key is NOT shown again; "Key already issued — contact support to rotate" message shown

---

### AC-12: Subscriber has a defined path if they lose their API key
**Given** a subscriber did not save their API key
**When** they contact support or navigate to an account recovery flow
**Then** they can request a key rotation (old key deactivated, new key generated and shown once)
  and the rotation requires identity verification

**Notes:** [BUILD REQUIRED] No self-serve key rotation exists today. Policy decision needed before implementing.

---

## Acceptance Criteria: Web UI Scraper — pagefetch.com

### AC-1: Happy path — authenticated user scrapes a URL and downloads results
**Given** the user has a valid session or saved API key
**When** they enter a valid URL and click START SCRAPING
**Then** the START SCRAPING button becomes disabled and the STOP button becomes active
  and a progress indicator appears showing scraping activity
  and upon completion the DOWNLOAD ZIP button becomes active
  and clicking DOWNLOAD ZIP initiates a file download

**Edge cases:**
- User enters a URL with trailing whitespace — UI trims it silently
- User pastes a URL without a protocol — UI normalizes to `https://` or shows inline validation error
- User double-clicks START SCRAPING — second click is a no-op

---

### AC-2: Anonymous user hits the scraper — auth gate
**Given** the user has no API key stored
**When** they enter a URL and click START SCRAPING
**Then** the UI displays a clear message explaining that an account or API key is required
  and two affordances are presented: a "Sign Up" button and an "Enter API Key" option
  and the TARGET URL field retains the URL the user entered

**Edge cases:**
- Session expires mid-session — 401 response triggers the auth gate message, not a silent failure

**Notes:** [BUILD REQUIRED] Auth gate modal or inline banner does not currently exist.

---

### AC-3: Logged-in user — API key is transparently attached to requests
**Given** the user has a saved API key in the browser
**When** they initiate a scrape
**Then** the `X-API-Key` header is automatically included in the `POST /api/scrape` request
  and the user sees no auth-related prompts or interruptions

**Notes:** [BUILD REQUIRED] Key storage and injection mechanism needs to be implemented.

---

### AC-4: Progress feedback during a long scrape
**Given** the user has started a scrape job
**When** the SSE progress stream is active
**Then** the progress indicator updates in real time without a page reload
  and the user can see at minimum: number of URLs processed vs. total
  and the STOP button remains active throughout

**Edge cases:**
- SSE connection drops mid-scrape — UI displays a reconnecting state and attempts to reattach
- Scrape completes extremely quickly — progress indicator still appears briefly

---

### AC-5: User cancels a scrape mid-job
**Given** a scrape job is in progress
**When** the user clicks the STOP button
**Then** a `POST /cancel/{tracker_id}` request is sent immediately
  and the progress indicator shows a "Cancelled" or "Stopped" state
  and the START SCRAPING button becomes active again

**Edge cases:**
- User clicks STOP after the job has already completed — button is a no-op
- Cancel request fails — UI shows a warning that cancellation may not have taken effect

---

### AC-6: Error state — invalid URL entered
**Given** the user is on the scraper page
**When** they enter a value that is not a valid URL and click START SCRAPING
**Then** the request is NOT submitted to the API
  and an inline validation message appears adjacent to the TARGET URL field
  and focus is returned to the TARGET URL field

---

### AC-7: Error state — target site is unreachable or returns an error
**Given** the user has submitted a valid URL
**When** the scraper fails to retrieve the target page
**Then** the progress indicator stops and displays a user-readable error message
  and the DOWNLOAD ZIP button does NOT become active
  and the START SCRAPING button becomes active again

---

### AC-8: Error state — no content found at valid URL
**Given** the user has submitted a valid, reachable URL
**When** the scraped page contains no usable content
**Then** the progress indicator stops and displays a specific, distinct message from the "site unreachable" error
  (e.g. "We reached the page but couldn't extract any content. The site may require JavaScript or a login.")
  and the DOWNLOAD ZIP button does NOT become active

**Notes:** Conflating "site down" with "content extraction failed" causes user confusion. These must be separate messages.

---

### AC-9: Error state — rate limit hit
**Given** the user has hit their request rate limit
**When** the rate limit is exceeded
**Then** the UI displays a clear, friendly message explaining the rate limit
  and includes an approximate wait time
  and the START SCRAPING button remains disabled until the rate limit clears

**Notes:** [BUILD REQUIRED] Rate limit feedback does not appear to exist in the current UI.

---

### AC-10: Branding consistency — "LINK SCRAPER" vs. pagefetch.com
**Given** a user arrives at pagefetch.com
**When** they land on the scraper page
**Then** the page title in the browser tab reads "pagefetch.com" or "PageFetch — Web Scraper"
  and the primary branding is consistent with the domain

**Notes:** Recommended resolution: adopt "PageFetch" as the product name, use "Link Scraper" as descriptor. Flag for product owner sign-off before any rename.
