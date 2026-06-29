"""Placeholder EPIC scheduling provider."""

from __future__ import annotations

from datetime import date

from ..models.session import Session
from .base import ScheduleProvider


class EpicScheduleProvider(ScheduleProvider):
    """Stub implementation for future EPIC integration."""

    def get_sessions(self, start_date: date, end_date: date) -> list[Session]:
        """Return sessions from EPIC once integrated."""
        # TODO: implement EPIC API integration.
        raise NotImplementedError
