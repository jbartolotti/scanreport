"""Helpers for deriving lightweight DICOM-related session timing metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta
from typing import Any

from ..models.session import Session


def compute_signature(session: Session) -> str:
    """Create a deterministic signature from scan names and DICOM counts."""
    payload = {
        "session_id": session.session_id,
        "project_id": session.project_id,
        "scans": [
            {"sequence_name": scan.sequence_name, "dicom_count": scan.dicom_count}
            for scan in session.scans
        ],
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def compute_session_times(session: Session) -> tuple[datetime, datetime, int]:
    """Compute session start/end times and DICOM count using lightweight heuristics.

    The real implementation will eventually read DICOM headers and extract
    AcquisitionTime / ContentTime values from the underlying files. For now,
    this function uses stable metadata and a deterministic placeholder schedule.
    """
    if session.start_time is not None:
        start_time = session.start_time
    else:
        # TODO: read DICOM headers and extract AcquisitionTime / ContentTime.
        start_time = datetime.combine(session.date, time(hour=8, minute=0))

    if session.end_time is not None:
        end_time = session.end_time
    else:
        end_time = start_time + timedelta(minutes=max(5, len(session.scans) * 3))

    dicom_count = sum(scan.dicom_count for scan in session.scans)
    if dicom_count <= 0:
        # TODO: replace with real DICOM file counting once the scanner data path is available.
        dicom_count = max(1, len(session.scans) * 10)

    return start_time, end_time, dicom_count
