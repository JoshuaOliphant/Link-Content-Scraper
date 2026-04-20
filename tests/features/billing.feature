Feature: Billing and subscription lifecycle
  As a customer of pagefetch.com
  I want the billing and API key system to work reliably
  So that I can subscribe, use the API, and have my access managed correctly

  # ── Checkout ──────────────────────────────────────────────────────────────────

  Scenario: Successful checkout provisions an API key claimable once
    Given a checkout.session.completed webhook fires for a new starter subscriber
    When the webhook is delivered to the API
    Then the customer record exists in the database
    And the API key can be claimed once by session ID
    And claiming the API key a second time returns 404

  # ── Normal usage ──────────────────────────────────────────────────────────────

  Scenario: Active subscriber can use their API key
    Given an active starter subscriber with a valid API key
    When they submit a scrape request with their API key
    Then the scrape request succeeds with status 200

  # ── Quota enforcement ─────────────────────────────────────────────────────────

  Scenario: Subscriber who exhausted their quota receives a 429 with resetsAt
    Given an active starter subscriber with a valid API key
    And the subscriber has consumed their entire monthly quota
    When they submit a scrape request with their API key
    Then the response is 429 Too Many Requests
    And the response body contains error, detail, and resetsAt fields

  # ── Payment failure ───────────────────────────────────────────────────────────

  Scenario: Payment failure deactivates the API key immediately
    Given an active starter subscriber with a valid API key
    When an invoice.payment_failed webhook fires for that subscriber
    Then subsequent scrape requests with their API key return 401

  # ── Reactivation ─────────────────────────────────────────────────────────────

  Scenario: Successful payment reactivates a deactivated API key
    Given an active starter subscriber with a valid API key
    And an invoice.payment_failed webhook has deactivated their key
    When an invoice.payment_succeeded webhook fires for that subscriber
    Then subsequent scrape requests with their API key return 200

  # ── Cancellation ─────────────────────────────────────────────────────────────

  Scenario: Subscription cancellation deactivates the API key
    Given an active starter subscriber with a valid API key
    When a customer.subscription.deleted webhook fires for that subscriber
    Then subsequent scrape requests with their API key return 401

  # ── Tier upgrade ─────────────────────────────────────────────────────────────

  Scenario: Tier upgrade immediately expands quota
    Given an active starter subscriber with a valid API key
    And the subscriber has consumed their entire monthly quota
    When a customer.subscription.updated webhook fires upgrading them to pro
    Then subsequent scrape requests with their API key return 200
