"""Scan model definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Scan:
    """Represents a single scan captured for a session."""

    sequence_name: str
    normalized_name: str
    dicom_count: int = 0
    sequence_number: str | int | None = None
    protocol_name: str | None = None
    series_description: str | None = None
    start_time: object | None = None
    start_date: object | None = None
    frames: float | int | None = None
    tr: float | None = None
