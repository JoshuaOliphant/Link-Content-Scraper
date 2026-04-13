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
