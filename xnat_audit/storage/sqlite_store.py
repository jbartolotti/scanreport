"""Lightweight SQLite-backed cache for session timing metadata."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SessionTimeStore:
    """Persist session timing metadata in a local SQLite database."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        """Create the backing table if it does not already exist."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_times (
                session_id TEXT PRIMARY KEY,
                project_id TEXT,
                state TEXT,
                start_time TEXT,
                end_time TEXT,
                dicom_count INTEGER,
                signature TEXT,
                last_checked TEXT
            )
            """
        )
        self.connection.commit()

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Return the cached record for a session if one exists."""
        row = self.connection.execute(
            "SELECT session_id, project_id, state, start_time, end_time, dicom_count, signature, last_checked FROM session_times WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def upsert(self, record: dict[str, Any]) -> None:
        """Insert or update a session timing record."""
        self.connection.execute(
            """
            INSERT INTO session_times (
                session_id, project_id, state, start_time, end_time, dicom_count, signature, last_checked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                project_id = excluded.project_id,
                state = excluded.state,
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                dicom_count = excluded.dicom_count,
                signature = excluded.signature,
                last_checked = excluded.last_checked
            """,
            (
                record["session_id"],
                record.get("project_id"),
                record.get("state"),
                record.get("start_time"),
                record.get("end_time"),
                record.get("dicom_count"),
                record.get("signature"),
                record.get("last_checked"),
            ),
        )
        self.connection.commit()

    def has_changed(self, session_id: str, signature: str) -> bool:
        """Return True when a session is new or its signature differs from the cache."""
        cached = self.get(session_id)
        if cached is None:
            return True
        return cached.get("signature") != signature

    def mark_checked(self, session_id: str) -> None:
        """Update the last_checked timestamp without changing the cached payload."""
        self.connection.execute(
            "UPDATE session_times SET last_checked = ? WHERE session_id = ?",
            (self._now(), session_id),
        )
        self.connection.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        self.connection.close()

    def _now(self) -> str:
        import datetime as dt

        return dt.datetime.now(dt.timezone.utc).isoformat()
