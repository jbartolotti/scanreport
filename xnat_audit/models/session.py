"""Session model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .enums import SessionOrigin, SessionState
from .scan import Scan


@dataclass
class Session:
    """Normalized representation of an XNAT session."""

    subject_id: str
    project_id: str
    session_id: str
    date: date
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    origin: SessionOrigin = SessionOrigin.INTERNAL
    state: SessionState = SessionState.PREARCHIVE
    scans: list[Scan] = field(default_factory=list)
