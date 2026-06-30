"""Normalization routines for raw XNAT session payloads."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Mapping

from ..models.enums import SessionOrigin, SessionState
from ..models.scan import Scan
from ..models.session import Session
from ..utils import coerce_date
from .naming import normalize_sequence_name

logger = logging.getLogger(__name__)
_NORMALIZE_DEBUG_COUNT = 0


def normalize_session(raw: Mapping[str, Any]) -> Session:
    """Convert a raw XNAT record into the internal Session model."""

    session_date = raw.get("date")
    parsed_date = coerce_date(session_date) or date.today()

    raw_scans = list(raw.get("scans", []))
    scans = [
        Scan(
            sequence_name=scan.get("sequence_name", ""),
            normalized_name=normalize_sequence_name(str(scan.get("sequence_name", ""))),
            dicom_count=int(scan.get("dicom_count", 0) or 0),
        )
        for scan in raw_scans
    ]

    global _NORMALIZE_DEBUG_COUNT
    if logger.isEnabledFor(logging.DEBUG) and _NORMALIZE_DEBUG_COUNT < 3:
        session_id = str(raw.get("session_id", ""))
        logger.debug(
            "normalize_session: session_id=%s raw_scans=%d normalized_scans=%d",
            session_id,
            len(raw_scans),
            len(scans),
        )
        if scans:
            first_scan = scans[0]
            logger.debug(
                "normalized first scan: sequence_name=%s dicom_count=%d protocol_name=%s frames=%s tr=%s",
                first_scan.sequence_name,
                first_scan.dicom_count,
                None,
                None,
                None,
            )
        _NORMALIZE_DEBUG_COUNT += 1

    return Session(
        subject_id=str(raw.get("subject_id", "")),
        project_id=str(raw.get("project_id", "")),
        session_id=str(raw.get("session_id", "")),
        date=parsed_date,
        origin=SessionOrigin(str(raw.get("origin", SessionOrigin.INTERNAL.value)).upper()),
        state=SessionState(str(raw.get("state", SessionState.PREARCHIVE.value)).upper()),
        scans=scans,
    )
