"""Scan model definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Scan:
    """Represents a single scan captured for a session."""

    sequence_name: str
    normalized_name: str
    dicom_count: int = 0
