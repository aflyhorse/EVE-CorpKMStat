"""
Utility functions for the application.
"""

import re
import calendar


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
