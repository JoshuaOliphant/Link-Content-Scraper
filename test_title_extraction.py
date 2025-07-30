#!/usr/bin/env python3
"""Test script for title extraction and safe filename generation"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import extract_title_from_content, create_safe_filename

def test_title_extraction():
    """Test various content formats for title extraction"""
    
    test_cases = [
        # Test case 1: Standard H1 header
        {
            "content": """# Introduction to Machine Learning

This is a comprehensive guide to machine learning basics.

## Chapter 1: Getting Started

Machine learning is...""",
            "expected_title": "Introduction to Machine Learning"
        },
        
        # Test case 2: Title with metadata
        {
            "content": """URL Source: https://example.com/article
Title: Understanding Neural Networks

# Understanding Neural Networks

Neural networks are computational models...""",
            "expected_title": "Understanding Neural Networks"
        },
        
        # Test case 3: H2 header only
        {
            "content": """Some introductory text without header

## FastAPI Documentation

FastAPI is a modern web framework...""",
            "expected_title": "FastAPI Documentation"
        },
        
        # Test case 4: Title with markdown formatting
        {
            "content": """# [Getting Started with **Python**](https://python.org)

Python is a versatile programming language...""",
            "expected_title": "Getting Started with Python"
        },
        
        # Test case 5: No title
        {
            "content": """URL Source: https://example.com
            
Just some content without any headers.""",
            "expected_title": None
        },
        
        # Test case 6: arXiv paper format
        {
            "content": """# Attention Is All You Need

Published: 2017-06-12

## Abstract

The dominant sequence transduction models...""",
            "expected_title": "Attention Is All You Need"
        }
    ]
    
    print("Testing title extraction...")
    print("-" * 50)
    
    all_passed = True
    for i, test in enumerate(test_cases, 1):
        extracted = extract_title_from_content(test["content"])
        passed = extracted == test["expected_title"]
        status = "✓" if passed else "✗"
        
        print(f"Test {i}: {status}")
        print(f"  Expected: {test['expected_title']}")
        print(f"  Got: {extracted}")
        
        if not passed:
            all_passed = False
        print()
    
    return all_passed

def test_safe_filename_creation():
    """Test safe filename generation"""
    
    test_cases = [
        # Test case 1: Normal title
        {
            "title": "Introduction to Machine Learning",
            "url": "https://example.com/ml-intro",
            "expected_pattern": r"Introduction-to-Machine-Learning_\d{8}\.md"
        },
        
        # Test case 2: Title with special characters
        {
            "title": "What's New in Python 3.12?",
            "url": "https://python.org/whats-new",
            "expected_pattern": r"Whats-New-in-Python-312_\d{8}\.md"
        },
        
        # Test case 3: Very long title
        {
            "title": "A Comprehensive Guide to Understanding and Implementing Advanced Machine Learning Algorithms for Natural Language Processing Applications in Production Environments",
            "url": "https://example.com/long-article",
            "expected_pattern": r"A-Comprehensive-Guide-to-Understanding-and-Implementing-Advanced-Machine-Learning-Algorithms-for-Nat_\d{8}\.md"
        },
        
        # Test case 4: No title (fallback to hash)
        {
            "title": None,
            "url": "https://example.com/no-title",
            "expected_pattern": r"-?\d+\.md"
        },
        
        # Test case 5: Unicode title
        {
            "title": "Café: A Guide to Émigré Literature",
            "url": "https://example.com/unicode",
            "expected_pattern": r"Cafe-A-Guide-to-Emigre-Literature_\d{8}\.md"
        },
        
        # Test case 6: Title with only special characters
        {
            "title": "!!!???###",
            "url": "https://example.com/special",
            "expected_pattern": r"untitled_\d{8}\.md"
        }
    ]
    
    print("\nTesting safe filename creation...")
    print("-" * 50)
    
    import re
    all_passed = True
    
    for i, test in enumerate(test_cases, 1):
        filename = create_safe_filename(test["title"], test["url"])
        pattern = test["expected_pattern"]
        matches = bool(re.match(pattern, filename))
        status = "✓" if matches else "✗"
        
        print(f"Test {i}: {status}")
        print(f"  Title: {test['title']}")
        print(f"  Generated: {filename}")
        print(f"  Pattern: {pattern}")
        
        # Additional checks
        if matches:
            # Check filename is valid
            invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
            has_invalid = any(char in filename for char in invalid_chars)
            if has_invalid:
                print(f"  WARNING: Filename contains invalid characters!")
                all_passed = False
                
            # Check length
            if len(filename) > 255:  # Most filesystems limit
                print(f"  WARNING: Filename too long ({len(filename)} chars)!")
                all_passed = False
        else:
            all_passed = False
            
        print()
    
    return all_passed

def main():
    """Run all tests"""
    print("=" * 50)
    print("Title Extraction and Filename Generation Tests")
    print("=" * 50)
    
    title_tests_passed = test_title_extraction()
    filename_tests_passed = test_safe_filename_creation()
    
    print("\n" + "=" * 50)
    if title_tests_passed and filename_tests_passed:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())