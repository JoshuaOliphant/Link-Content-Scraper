#!/usr/bin/env python3
"""Integration test for the title preservation feature"""

import sys
import os
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import create_zip_file, extract_title_from_content, create_safe_filename

def test_zip_file_creation_with_titles():
    """Test that ZIP files are created with proper title-based filenames"""
    
    # Simulate scraped content with various titles
    test_contents = [
        (
            "https://example.com/ml-guide",
            """# Machine Learning: A Beginner's Guide

## Introduction

Machine learning is a fascinating field that enables computers to learn from data.

### What You'll Learn

1. Basic concepts of ML
2. Common algorithms
3. Practical applications

This guide will take you through the fundamentals step by step."""
        ),
        (
            "https://docs.python.org/3/tutorial/",
            """Title: The Python Tutorial

# The Python Tutorial

Python is an easy to learn, powerful programming language. It has efficient high-level data structures and a simple but effective approach to object-oriented programming.

## 1. Whetting Your Appetite

If you do much work on computers, eventually you find that there's some task you'd like to automate."""
        ),
        (
            "https://arxiv.org/abs/1706.03762",
            """# Attention Is All You Need

Published: 2017-06-12

## Abstract

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder."""
        ),
        (
            "https://example.com/no-title-page",
            """URL Source: https://example.com/no-title-page

This page doesn't have a proper title header.

It just contains some content without any markdown headers.

But it should still be saved with a hash-based filename."""
        )
    ]
    
    # Create a temporary job ID and tracker ID
    job_id = "test-job-123"
    tracker_id = "test-tracker-456"
    
    try:
        # Create ZIP file
        zip_path = create_zip_file(test_contents, job_id, tracker_id)
        
        print("Testing ZIP file creation with title-based filenames...")
        print("-" * 50)
        
        # Verify ZIP file exists
        assert Path(zip_path).exists(), f"ZIP file not created at {zip_path}"
        print("✓ ZIP file created successfully")
        
        # Extract and check filenames
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            filenames = zipf.namelist()
            print(f"\n✓ Found {len(filenames)} files in ZIP:")
            
            expected_patterns = {
                "Machine-Learning-A-Beginners-Guide": "Should contain ML guide title",
                "The-Python-Tutorial": "Should contain Python tutorial title",
                "Attention-Is-All-You-Need": "Should contain Attention paper title",
            }
            
            for filename in filenames:
                print(f"  - {filename}")
                
                # Check if any expected pattern is in the filename
                found_pattern = False
                for pattern, description in expected_patterns.items():
                    if pattern in filename:
                        print(f"    ✓ {description}")
                        found_pattern = True
                        break
                
                if not found_pattern and not filename.endswith(".md"):
                    print(f"    ⚠ Unexpected filename format")
                
                # Verify file has .md extension
                assert filename.endswith(".md"), f"File {filename} doesn't have .md extension"
                
                # Verify no invalid characters
                invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
                for char in invalid_chars:
                    assert char not in filename, f"Filename {filename} contains invalid character: {char}"
            
            print("\n✓ All filenames are valid")
            
            # Check file contents
            print("\nChecking file contents...")
            for filename in filenames:
                with zipf.open(filename) as f:
                    content = f.read().decode('utf-8')
                    # Verify content starts with original URL
                    assert content.startswith("# Original URL:"), f"File {filename} doesn't start with URL header"
                    print(f"  ✓ {filename}: Content properly formatted")
        
        # Clean up
        Path(zip_path).unlink()
        print("\n✓ Cleanup completed")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_edge_cases():
    """Test edge cases for filename generation"""
    
    print("\n\nTesting edge cases...")
    print("-" * 50)
    
    edge_cases = [
        {
            "desc": "Very long title (200+ chars)",
            "content": "# " + "A" * 200 + "\n\nContent here",
            "url": "https://example.com/long"
        },
        {
            "desc": "Title with file extensions",
            "content": "# README.md and CONFIG.yaml Guide\n\nContent",
            "url": "https://example.com/files"
        },
        {
            "desc": "Title with path separators",
            "content": "# Unix/Linux vs Windows\\Path Guide\n\nContent",
            "url": "https://example.com/paths"
        },
        {
            "desc": "Empty content",
            "content": "",
            "url": "https://example.com/empty"
        }
    ]
    
    all_passed = True
    for case in edge_cases:
        print(f"\nTesting: {case['desc']}")
        title = extract_title_from_content(case['content'])
        filename = create_safe_filename(title, case['url'])
        
        print(f"  Title: {title}")
        print(f"  Filename: {filename}")
        
        # Verify filename is valid
        if not filename.endswith('.md'):
            print("  ✗ Missing .md extension")
            all_passed = False
        
        if len(filename) > 255:
            print(f"  ✗ Filename too long: {len(filename)} chars")
            all_passed = False
        
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        invalid_found = [c for c in invalid_chars if c in filename]
        if invalid_found:
            print(f"  ✗ Contains invalid characters: {invalid_found}")
            all_passed = False
        
        if not invalid_found and len(filename) <= 255 and filename.endswith('.md'):
            print("  ✓ Valid filename")
    
    return all_passed

def main():
    """Run all integration tests"""
    print("=" * 50)
    print("Integration Tests for Title Preservation Feature")
    print("=" * 50)
    
    zip_test_passed = test_zip_file_creation_with_titles()
    edge_test_passed = test_edge_cases()
    
    print("\n" + "=" * 50)
    if zip_test_passed and edge_test_passed:
        print("✓ All integration tests passed!")
        return 0
    else:
        print("✗ Some integration tests failed!")
        return 1

if __name__ == "__main__":
    # Need to initialize progress_tracker for the test
    from collections import defaultdict
    from main import progress_tracker
    
    sys.exit(main())