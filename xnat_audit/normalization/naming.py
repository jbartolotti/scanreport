"""Sequence-name normalization helpers."""

from __future__ import annotations


def normalize_sequence_name(name: str) -> str:
    """Normalize a DICOM or XNAT sequence name into a stable identifier."""
    normalized = name.strip().lower()
    # TODO: add mapping for known scanner naming variations.
    return normalized.replace(" ", "_")
