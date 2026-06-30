"""Shared helpers for common date coercion across the package."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def coerce_date(value: Any) -> date | None:
    """Parse common XNAT-style date and datetime values into a date object."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()
    if not value:
        return None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%d-%b-%Y",
        "%d-%B-%Y",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None
