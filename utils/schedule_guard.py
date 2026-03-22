from __future__ import annotations

from datetime import datetime, timedelta

SEND_HOUR_START = 8
SEND_HOUR_END = 20


def normalize_send_window(start_hour: int | None, end_hour: int | None) -> tuple[int, int]:
    start = SEND_HOUR_START if start_hour is None else int(start_hour)
    end = SEND_HOUR_END if end_hour is None else int(end_hour)
    if not (0 <= start <= 23 and 1 <= end <= 24 and start < end):
        return SEND_HOUR_START, SEND_HOUR_END
    return start, end


def within_send_window(now: datetime, start_hour: int | None = None, end_hour: int | None = None) -> bool:
    start, end = normalize_send_window(start_hour, end_hour)
    return start <= now.hour < end


def seconds_until_next_window(now: datetime, start_hour: int | None = None, end_hour: int | None = None) -> int:
    start, end = normalize_send_window(start_hour, end_hour)
    if within_send_window(now, start, end):
        return 0
    if now.hour >= end:
        next_window = (now + timedelta(days=1)).replace(hour=start, minute=0, second=0, microsecond=0)
    else:
        next_window = now.replace(hour=start, minute=0, second=0, microsecond=0)
    return max(1, int((next_window - now).total_seconds()))
