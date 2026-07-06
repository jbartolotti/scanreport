"""Helpers for deriving lightweight DICOM-related session timing metadata."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, time, timedelta
from typing import Any

from ..models.session import Session
from ..utils import coerce_datetime


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

from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


def compute_session_times(
    session: Session,
) -> tuple[datetime | None, datetime | None, int, str]:
    """
    Compute session timing and derive a scan profile.

    Session start:
        Earliest scan startTime.

    Session end:
        Latest scan startTime plus estimated duration.

    Duration estimate:
        frames * TR (when both are available).

    Returns:
        start_time
        end_time
        total_dicom_count
        scan_profile_json
    """

    session_start = None
    session_end = None
    total_dicom_count = 0

    profile = []

    for scan in session.scans:


        logger.debug(
            "scan=%s start_time_pre=%r frames=%r tr=%r dicom_count=%r",
            getattr(scan, "sequence_name", None),
            getattr(scan, "start_time", None),
            getattr(scan, "frames", None),
            getattr(scan, "tr", None),
            getattr(scan, "dicom_count", None),
        )


        total_dicom_count += max(0, scan.dicom_count)

        scan_start = getattr(scan, "start_time", None)
        if isinstance(scan_start, str):
            scan_start = coerce_datetime(scan_start)
        logger.debug(
            "Parsed start_time %r -> %r",
            getattr(scan, "start_time", None),
            scan_start,
        )
        frames = getattr(scan, "frames", None)
        tr = getattr(scan, "tr", None)

        scan_end = None

        if (
            scan_start is not None
            and frames is not None
            and tr is not None
        ):
            try:
                duration_seconds = (
                    float(frames) * float(tr)
                ) / 1000.0

                scan_end = scan_start + timedelta(
                    seconds=duration_seconds
                )
            except Exception:
                scan_end = scan_start

        elif scan_start is not None:
            scan_end = scan_start

        profile.append(
            {
                "sequence_id": getattr(scan, "sequence_id", None),

                # Human-facing names
                "series_description": getattr(
                    scan,
                    "series_description",
                    None,
                ),
                "protocol_name": getattr(
                    scan,
                    "protocol_name",
                    None,
                ),
                "sequence_name": getattr(
                    scan,
                    "sequence_name",
                    None,
                ),
                "normalized_name": getattr(
                    scan,
                    "normalized_name",
                    None,
                ),

                # Timing
                "start_time": (
                    scan_start.isoformat()
                    if scan_start
                    else None
                ),

                # Size / completeness metrics
                "file_count": scan.dicom_count,
                "frames": frames,
                "tr": tr,

                # Useful later for scanner-specific profiles
                "scanner": getattr(scan, "scanner", None),
                "scanner_model": getattr(
                    scan,
                    "scanner_model",
                    None,
                ),
            }
        )

        if scan_start is not None:
            if (
                session_start is None
                or scan_start < session_start
            ):
                session_start = scan_start

        if scan_end is not None:
            if (
                session_end is None
                or scan_end > session_end
            ):
                session_end = scan_end

    return (
        session_start,
        session_end,
        total_dicom_count,
        json.dumps(profile),
    )