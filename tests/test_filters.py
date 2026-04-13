# ABOUTME: Tests for URL filtering and arXiv URL transformation.
# ABOUTME: Covers should_skip_url, transform_arxiv_url, and is_pdf_url.

import pytest

from link_content_scraper.filters import is_pdf_url, should_skip_url, transform_arxiv_url


class TestShouldSkipUrl:
    @pytest.mark.parametrize("url", [
        "https://twitter.com/user/status/123",
        "https://x.com/user",
        "https://www.linkedin.com/in/someone",
        "https://facebook.com/page",
        "https://instagram.com/user",
        "https://youtube.com/watch?v=abc",
        "https://substackcdn.com/image.png",
        "https://example.com/photo.jpg",
        "https://example.com/photo.PNG",
        "https://example.com/image.gif",
        "https://example.com/image.webp",
    ])
    def test_skip(self, url):
        assert should_skip_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://example.com/article",
        "https://docs.python.org/3/",
        "https://arxiv.org/abs/2301.00001",
        "https://blog.example.com/post",
    ])
    def test_no_skip(self, url):
        assert should_skip_url(url) is False


class TestTransformArxivUrl:
    def test_abs_url(self):
        assert transform_arxiv_url("https://arxiv.org/abs/2301.00001") == \
            "https://arxiv.org/pdf/2301.00001.pdf"

    def test_abs_url_with_version(self):
        assert transform_arxiv_url("https://arxiv.org/abs/2301.00001v2") == \
            "https://arxiv.org/pdf/2301.00001v2.pdf"

    def test_html_url(self):
        assert transform_arxiv_url("https://arxiv.org/html/2301.00001") == \
            "https://arxiv.org/pdf/2301.00001.pdf"

    def test_already_pdf(self):
        url = "https://arxiv.org/pdf/2301.00001.pdf"
        assert transform_arxiv_url(url) == url

    def test_non_arxiv(self):
        url = "https://example.com/paper"
        assert transform_arxiv_url(url) == url


class TestIsPdfUrl:
    def test_pdf_extension(self):
        assert is_pdf_url("https://example.com/paper.pdf") is True

    def test_arxiv_pdf(self):
        assert is_pdf_url("https://arxiv.org/pdf/2301.00001.pdf") is True

    def test_non_pdf(self):
        assert is_pdf_url("https://example.com/article") is False
