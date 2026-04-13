# ABOUTME: Entry point for the Link Content Scraper application.
# ABOUTME: Thin wrapper so that "uvicorn main:app" works; all logic is in the package.

from link_content_scraper.app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
