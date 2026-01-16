"""
Utility functions for the application.
"""

import re
import calendar
from typing import Optional


def prefers_zh(request) -> bool:
    """
    Detect if the request likely prefers Chinese based on headers/UA.
    """
    if request is None:
        return False

    def _lower(value: Optional[str]) -> str:
        return value.lower() if isinstance(value, str) else ""

    accept_lang = _lower(request.headers.get("Accept-Language"))
    user_agent = _lower(request.headers.get("User-Agent"))
    env_lang = _lower(request.environ.get("HTTP_ACCEPT_LANGUAGE"))

    lang_blob = " ".join([accept_lang, env_lang, user_agent])

    # Common patterns: zh, zh-cn, zh-hans, zh-hant
    return "zh" in lang_blob


def detect_color(text):
    """
    Detect if text contains a color tag and return tuple (text, color)
    Example: "<color=0xFFBF68FF>月影</color>" returns ("月影", "#BF68FF")
    """
    pattern = r"<color=(0x[A-Fa-f0-9]{6,8})>(.*?)</color>"
    match = re.search(pattern, text)
    if match:
        color_hex = match.group(1)
        name = match.group(2)
        # Convert 0xFFBF68FF to #BF68FF (strip alpha channel if present)
        web_color = "#" + color_hex[4:10]
        return (name, web_color)
    return (text, None)


def get_last_day_of_month(year, month):
    """Get the last day of the given month in the given year."""
    try:
        return calendar.monthrange(int(year), int(month))[1]
    except (ValueError, TypeError):
        return 31  # fallback to maximum possible day
