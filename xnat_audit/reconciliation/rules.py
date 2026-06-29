"""Configurable reconciliation rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReconciliationRules:
    """Container for anomaly-detection configuration."""

    minimum_dicom_count: int = 1
    require_expected_sequences: bool = True
    allow_duplicate_sequences: bool = False

    # TODO: load these values from configuration files or environment variables.
