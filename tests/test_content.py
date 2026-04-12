"""Tests for title extraction, filename generation, and content validation."""

import re

import pytest

from link_content_scraper.content import (
    create_safe_filename,
    extract_title_from_content,
    is_content_valid,
)


# -- extract_title_from_content ------------------------------------------------

class TestExtractTitle:
    def test_h1_header(self):
        content = "# Introduction to Machine Learning\n\nSome body text."
        assert extract_title_from_content(content) == "Introduction to Machine Learning"

    def test_title_metadata(self):
        content = (
            "URL Source: https://example.com/article\n"
            "Title: Understanding Neural Networks\n\n"
            "# Understanding Neural Networks\n\nBody."
        )
        assert extract_title_from_content(content) == "Understanding Neural Networks"

    def test_h2_fallback(self):
        content = "Some text without header\n\n## FastAPI Documentation\n\nBody."
        assert extract_title_from_content(content) == "FastAPI Documentation"

    def test_markdown_formatting_stripped(self):
        content = "# [Getting Started with **Python**](https://python.org)\n\nBody."
        assert extract_title_from_content(content) == "Getting Started with Python"

    def test_no_title(self):
        content = "URL Source: https://example.com\n\nJust some text."
        assert extract_title_from_content(content) is None

    def test_empty_content(self):
        assert extract_title_from_content("") is None
        assert extract_title_from_content(None) is None

    def test_arxiv_paper(self):
        content = "# Attention Is All You Need\n\nPublished: 2017\n\n## Abstract\n\nBody."
        assert extract_title_from_content(content) == "Attention Is All You Need"


# -- create_safe_filename ------------------------------------------------------

class TestCreateSafeFilename:
    def test_normal_title(self):
        fn = create_safe_filename("Intro to ML", "https://example.com/ml")
        assert fn.endswith(".md")
        assert "Intro-to-ML" in fn

    def test_special_characters_removed(self):
        fn = create_safe_filename("What's New in Python 3.12?", "https://python.org")
        assert "?" not in fn
        assert "'" not in fn
        assert fn.endswith(".md")

    def test_long_title_truncated(self):
        fn = create_safe_filename("A" * 200, "https://example.com/long")
        # filename component (before _hash.md) should be <= 100
        parts = fn.rsplit("_", 1)
        assert len(parts[0]) <= 100

    def test_no_title_fallback(self):
        fn = create_safe_filename(None, "https://example.com/no-title")
        assert re.match(r"[a-f0-9]{12}\.md", fn)

    def test_unicode_normalized(self):
        fn = create_safe_filename("Cafe: A Guide to Emigre Literature", "https://example.com")
        assert fn.endswith(".md")

    def test_only_special_chars(self):
        fn = create_safe_filename("!!!???###", "https://example.com/special")
        assert fn.startswith("untitled_")

    def test_no_invalid_filesystem_chars(self):
        fn = create_safe_filename("Unix/Linux vs Windows\\Path", "https://example.com")
        invalid = set('/:*?"<>|\\')
        assert not invalid.intersection(fn)


# -- is_content_valid ----------------------------------------------------------

class TestIsContentValid:
    def test_valid_content(self):
        content = "# Title\n\nParagraph one.\n\nParagraph two with enough text to pass validation easily."
        assert is_content_valid(content) is True

    def test_empty(self):
        assert is_content_valid("") is False
        assert is_content_valid(None) is False

    def test_too_short(self):
        assert is_content_valid("short") is False

    def test_metadata_only(self):
        content = "# Original URL: https://x.com\nTitle: X\nURL Source: https://x.com\n"
        assert is_content_valid(content) is False
