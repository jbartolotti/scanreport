"""Application configuration helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class Settings:
    """Configuration values used by the audit package."""

    xnat_url: str = ""
    sqlite_db_path: str = "./data/session_times.db"
    lookback_days: int = 30
    netrc_host: str = "xnat"
    date_window_days: int = 7

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Settings":
        """Create settings from a mapping, preferring environment variables when present."""
        return cls(
            xnat_url=os.getenv("XNAT_URL") or str(data.get("xnat_url") or ""),
            sqlite_db_path=os.getenv("SQLITE_DB_PATH") or str(data.get("sqlite_db_path") or "./data/session_times.db"),
            lookback_days=_coerce_int(os.getenv("LOOKBACK_DAYS"), data.get("lookback_days"), 30),
            netrc_host=os.getenv("XNAT_NETRC_HOST") or str(data.get("netrc_host") or "xnat"),
            date_window_days=_coerce_int(os.getenv("DATE_WINDOW_DAYS"), data.get("date_window_days"), 7),
        )

    @classmethod
    def from_file(cls, path: str | Path | None) -> "Settings":
        """Create settings from a JSON file if the file exists."""
        if path is None:
            return cls.from_mapping({})

        config_path = Path(path)
        if not config_path.exists():
            return cls.from_mapping({})

        with config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_mapping(payload)


def _coerce_int(env_value: str | None, raw_value: Any, default: int) -> int:
    """Convert a value into an integer with a sensible fallback."""
    if env_value is not None and env_value != "":
        try:
            return int(env_value)
        except ValueError:
            return default
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value)
        except ValueError:
            return default
    return default


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load configuration from an optional JSON file, environment variables, or defaults."""
    if config_path is None:
        config_path = Path("config.json")
    return Settings.from_file(config_path)
