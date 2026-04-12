"""Entry point for the Link Content Scraper application.

Import the FastAPI app instance so that ``uvicorn main:app`` continues to work.
All logic lives inside the ``link_content_scraper`` package.
"""

from link_content_scraper.app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
