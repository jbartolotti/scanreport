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
    scans = []
    for scan in raw_scans:
        if not isinstance(scan, Mapping):
            continue
        sequence_name = str(scan.get("sequence_name", "") or "")
        frames_value = scan.get("frames")
        tr_value = scan.get("tr")
        raw_start_time = scan.get("start_time")
        logger.debug(
            "normalize_session start_time pre=%r",
            raw_start_time,
        )
        try:
            frames = float(frames_value) if frames_value not in (None, "") else None
        except (TypeError, ValueError):
            frames = None
        try:
            tr = float(tr_value) if tr_value not in (None, "") else None
        except (TypeError, ValueError):
            tr = None
        scans.append(
            Scan(
                sequence_name=sequence_name,
                normalized_name=normalize_sequence_name(sequence_name),
                dicom_count=int(scan.get("dicom_count", 0) or 0),
                sequence_number=scan.get("sequence_number"),
                protocol_name=scan.get("protocol_name"),
                series_description=scan.get("series_description"),
                start_time=raw_start_time,
                start_date=coerce_date(scan.get("start_date")),
                frames=frames,
                tr=tr,
            )
        )

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
                "normalize_session start_time post=%r",
                first_scan.start_time,
            )
            logger.debug(
                "normalized first scan: %s",
                {
                    "sequence_name": first_scan.sequence_name,
                    "dicom_count": first_scan.dicom_count,
                    "protocol_name": first_scan.protocol_name,
                    "series_description": first_scan.series_description,
                    "start_time": first_scan.start_time,
                    "start_date": first_scan.start_date,
                    "frames": first_scan.frames,
                    "tr": first_scan.tr,
                },
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
