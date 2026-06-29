"""Abstract scheduling provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..models.session import Session


class ScheduleProvider(ABC):
    """Interface for acquiring session schedules from external systems."""

    @abstractmethod
    def get_sessions(self, start_date: date, end_date: date) -> list[Session]:
        """Return scheduled sessions for the requested date range."""
        raise NotImplementedError
