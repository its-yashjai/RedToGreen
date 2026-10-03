"""Text helpers for product pages."""

import re


def slugify(title: str) -> str:
    """'Phone Case (Blue)!' -> 'phone-case-blue'"""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")


def truncate(text: str, limit: int, suffix: str = "...") -> str:
    """Cut text to at most `limit` characters, including the suffix."""
    if len(text) <= limit:
        return text
    return text[: limit - len(suffix)] + suffix


def count_words(text: str) -> int:
    return len(text.split())


def is_palindrome(text: str) -> bool:
    cleaned = "".join(ch.lower() for ch in text if ch.isalnum())
    return cleaned == cleaned[::-1]


def initials(name: str) -> str:
    """'ravi kumar sharma' -> 'RKS'"""
    return "".join(part[0].upper() for part in name.split())
