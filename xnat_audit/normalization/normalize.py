"""Normalization routines for raw XNAT session payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from ..models.enums import SessionOrigin, SessionState
from ..models.scan import Scan
from ..models.session import Session
from .naming import normalize_sequence_name


def normalize_session(raw: Mapping[str, Any]) -> Session:
    """Convert a raw XNAT record into the internal Session model."""
    session_date = raw.get("date")
    if isinstance(session_date, str):
        parsed_date = datetime.strptime(session_date, "%Y-%m-%d").date()
    elif isinstance(session_date, date):
        parsed_date = session_date
    else:
        parsed_date = date.today()

    scans = [
        Scan(
            sequence_name=scan.get("sequence_name", ""),
            normalized_name=normalize_sequence_name(str(scan.get("sequence_name", ""))),
            dicom_count=int(scan.get("dicom_count", 0) or 0),
        )
        for scan in raw.get("scans", [])
    ]

    return Session(
        subject_id=str(raw.get("subject_id", "")),
        project_id=str(raw.get("project_id", "")),
        session_id=str(raw.get("session_id", "")),
        date=parsed_date,
        origin=SessionOrigin(str(raw.get("origin", SessionOrigin.INTERNAL.value)).upper()),
        state=SessionState(str(raw.get("state", SessionState.PREARCHIVE.value)).upper()),
        scans=scans,
    )
