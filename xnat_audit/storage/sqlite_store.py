"""Lightweight SQLite-backed cache for session timing metadata."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionTimeStore:
    """Persist session timing metadata in a local SQLite database."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Opening SQLite database at %s (pid=%s)", self.db_path, os.getpid())
        self.connection = self._connect_with_retry()
        self.initialize()

    def _connect_with_retry(self) -> sqlite3.Connection:
        """Open a SQLite connection with retry logic for transient lock contention."""
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                connection = sqlite3.connect(str(self.db_path), timeout=30.0)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                connection.execute("PRAGMA foreign_keys = ON")
                logger.info("SQLite connection established for %s (attempt %d)", self.db_path, attempt)
                return connection
            except sqlite3.OperationalError as exc:
                last_error = exc
                self._log_operational_error(exc, "opening SQLite connection", attempt)
                if attempt == 3:
                    raise
                time.sleep(0.25 * attempt)

        if last_error is not None:
            raise last_error
        raise sqlite3.OperationalError("Unable to open SQLite connection")

    def initialize(self) -> None:
        """Create the backing table if it does not already exist."""
        logger.info("Initializing schema for %s", self.db_path)
        for attempt in range(1, 4):
            try:
                with self.connection:
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
                logger.info("SQLite schema initialized for %s", self.db_path)
                return
            except sqlite3.OperationalError as exc:
                self._log_operational_error(exc, "initializing schema", attempt)
                if attempt == 3:
                    raise
                time.sleep(0.25 * attempt)

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Return the cached record for a session if one exists."""
        row = self.connection.execute(
            "SELECT session_id, project_id, state, start_time, end_time, dicom_count, signature, last_checked FROM session_times WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def upsert(self, record: dict[str, Any]) -> None:
        """Insert or update a session timing record."""
        with self.connection:
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

    def has_changed(self, session_id: str, signature: str) -> bool:
        """Return True when a session is new or its signature differs from the cache."""
        cached = self.get(session_id)
        if cached is None:
            return True
        return cached.get("signature") != signature

    def mark_checked(self, session_id: str) -> None:
        """Update the last_checked timestamp without changing the cached payload."""
        with self.connection:
            self.connection.execute(
                "UPDATE session_times SET last_checked = ? WHERE session_id = ?",
                (self._now(), session_id),
            )

    def close(self) -> None:
        """Close the SQLite connection."""
        if getattr(self, "connection", None) is not None:
            logger.info("Closing SQLite connection for %s", self.db_path)
            self.connection.close()
            self.connection = None

    def _log_operational_error(self, exc: sqlite3.OperationalError, operation: str, attempt: int) -> None:
        """Emit structured diagnostics for SQLite failures."""
        message = str(exc).lower()
        if "database is locked" in message or "database table is locked" in message:
            logger.error(
                "SQLite lock detected while %s (attempt %d, path=%s): %s",
                operation,
                attempt,
                self.db_path,
                exc,
            )
        elif "unable to open database file" in message:
            logger.error(
                "SQLite file open failed while %s (attempt %d, path=%s): %s",
                operation,
                attempt,
                self.db_path,
                exc,
            )
        else:
            logger.error(
                "SQLite error while %s (attempt %d, path=%s): %s",
                operation,
                attempt,
                self.db_path,
                exc,
            )

    def _now(self) -> str:
        import datetime as dt

        return dt.datetime.now(dt.timezone.utc).isoformat()
