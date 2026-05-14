"""
Shared helper utilities.
"""

from __future__ import annotations


def truncate(text: str, max_len: int = 60) -> str:
    """Shorten a string with an ellipsis when it exceeds *max_len*."""
    return text if len(text) <= max_len else f"…{text[-(max_len - 1):]}"


def humanize_count(n: int, noun: str = "item") -> str:
    plural = "" if n == 1 else "s"
    return f"{n:,} {noun}{plural}"
