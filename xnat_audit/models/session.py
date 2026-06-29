"""Session model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from .enums import SessionOrigin, SessionState
from .scan import Scan


@dataclass(slots=True)
class Session:
    """Normalized representation of an XNAT session."""

    subject_id: str
    project_id: str
    session_id: str
    date: date
    start_time: Optional[time] = None
    origin: SessionOrigin = SessionOrigin.INTERNAL
    state: SessionState = SessionState.PREARCHIVE
    scans: list[Scan] = field(default_factory=list)
