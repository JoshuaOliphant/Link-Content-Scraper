"""Integration tests for ZIP creation and the scraper pipeline."""

import zipfile
from pathlib import Path

import pytest

from link_content_scraper.content import create_safe_filename, extract_title_from_content
from link_content_scraper.scraper import create_zip_file


class TestCreateZipFile:
    def test_creates_zip_with_titled_files(self, tmp_path):
        contents = [
            (
                "https://example.com/ml-guide",
                "# Machine Learning Guide\n\n## Intro\n\n"
                "ML is a fascinating field that enables computers to learn from data.\n"
                "It covers supervised and unsupervised approaches.",
            ),
            (
                "https://docs.python.org/3/tutorial/",
                "Title: The Python Tutorial\n\n# The Python Tutorial\n\n"
                "Python is an easy to learn language with efficient data structures.\n"
                "It supports object-oriented programming.",
            ),
        ]

        zip_path, count = create_zip_file(contents, "test-job")
        try:
            assert count == 2
            assert Path(zip_path).exists()
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert len(names) == 2
                for name in names:
                    assert name.endswith(".md")
                    assert "/" not in name and "\\" not in name
        finally:
            Path(zip_path).unlink(missing_ok=True)

    def test_skips_empty_content(self):
        contents = [
            ("https://example.com/empty", ""),
            (
                "https://example.com/real",
                "# Real Content\n\nThis is real content with enough words.\n"
                "It has multiple lines and paragraphs of text.",
            ),
        ]

        zip_path, count = create_zip_file(contents, "test-skip")
        try:
            assert count == 1
            with zipfile.ZipFile(zip_path) as zf:
                assert len(zf.namelist()) == 1
        finally:
            Path(zip_path).unlink(missing_ok=True)

    def test_raises_when_all_empty(self):
        contents = [("https://example.com/empty", "")]
        with pytest.raises(ValueError, match="No valid content"):
            create_zip_file(contents, "test-empty")


class TestEdgeCases:
    def test_very_long_title(self):
        content = "# " + "A" * 200 + "\n\nBody content here.\n\nMore content."
        title = extract_title_from_content(content)
        fn = create_safe_filename(title, "https://example.com/long")
        assert len(fn) <= 255
        assert fn.endswith(".md")

    def test_title_with_extensions(self):
        content = "# README.md and CONFIG.yaml Guide\n\nBody content.\n\nMore."
        title = extract_title_from_content(content)
        fn = create_safe_filename(title, "https://example.com/files")
        assert fn.endswith(".md")

    def test_title_with_path_separators(self):
        content = "# Unix/Linux vs Windows\\Path Guide\n\nBody.\n\nMore content."
        title = extract_title_from_content(content)
        fn = create_safe_filename(title, "https://example.com/paths")
        assert "/" not in fn
        assert "\\" not in fn
