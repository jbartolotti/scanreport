"""Application configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    """Configuration values used by the audit package."""

    base_url: str = ""
    netrc_host: str = "xnat"
    date_window_days: int = 7


def load_settings() -> Settings:
    """Load configuration from environment variables or defaults."""
    # TODO: support config file loading.
    return Settings()
