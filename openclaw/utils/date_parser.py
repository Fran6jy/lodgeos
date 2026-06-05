"""Robust date/time parsing utilities."""

import re
from datetime import datetime, timedelta, date
from typing import Optional


def parse_datetime(text: Optional[str], now: Optional[datetime] = None) -> datetime:
    """Parse a datetime string or natural language date to a datetime object."""
    if now is None:
        now = datetime.now()

    if not text:
        return now

    # Already ISO format
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pass

    text_lower = text.lower().strip()

    # Relative keywords
    if text_lower in ("today", "now"):
        return now
    if text_lower == "yesterday":
        return now - timedelta(days=1)
    if text_lower == "tomorrow":
        return now + timedelta(days=1)

    # "last monday" etc.
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, day in enumerate(days):
        if text_lower == f"last {day}":
            diff = (now.weekday() - i) % 7 or 7
            return now - timedelta(days=diff)

    # Time patterns: "09:00", "9am", "14:30"
    time_match = re.search(r"(\d{1,2}):(\d{2})", text)
    if time_match:
        h, m = int(time_match.group(1)), int(time_match.group(2))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    # Fallback: return now
    return now


def format_display(dt: datetime) -> str:
    return dt.strftime("%d %b %Y %H:%M")


def current_week_range(now: Optional[datetime] = None):
    if now is None:
        now = datetime.now()
    start = now - timedelta(days=now.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return start, end


def current_month_range(now: Optional[datetime] = None):
    if now is None:
        now = datetime.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        end = start.replace(year=now.year + 1, month=1) - timedelta(seconds=1)
    else:
        end = start.replace(month=now.month + 1) - timedelta(seconds=1)
    return start, end
