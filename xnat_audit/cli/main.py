"""Console entrypoint for the audit package."""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Sequence

from ..config.config import load_settings
from ..ingestion.client import XNATClient, ingest_sessions
from ..storage.sqlite_store import SessionTimeStore

logger = logging.getLogger("xnat_audit")


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure application logging level from CLI flags."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")
    else:
        root_logger.setLevel(level)
        for handler in root_logger.handlers:
            handler.setLevel(level)

    logger.setLevel(level)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="python -m xnat_audit")
    parser.add_argument("config_path", nargs="?", default=None, help="Path to a JSON config file (defaults to ./config.json)")
    parser.add_argument("--date", default=None, help="Target date for the audit run (YYYY-MM-DD)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging, including detailed SQLite step logs")
    parser.add_argument("--quiet", action="store_true", help="Suppress informational messages and only show warnings/errors")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose, quiet=args.quiet)

    config_path = args.config_path
    if config_path is None:
        config_path = Path("config.json")
        if not config_path.exists():
            config_path = None

    settings = load_settings(config_path)
    target_date = args.date or date.today().strftime("%Y-%m-%d")

    print(f"[xnat_audit] Starting audit run for {target_date}")
    logger.info("Starting audit run for %s", target_date)
    if config_path is None:
        print("[xnat_audit] No config file supplied; using built-in defaults")
        logger.info("No config file supplied; using built-in defaults")
    else:
        print(f"[xnat_audit] Using config file: {config_path}")
        logger.info("Using config file: %s", config_path)
    print(f"[xnat_audit] Loaded settings: xnat_url={settings.xnat_url or '<not set>'}, sqlite_db_path={settings.sqlite_db_path}")
    logger.info("Loaded settings: xnat_url=%s, sqlite_db_path=%s", settings.xnat_url or "<not set>", settings.sqlite_db_path)

    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[xnat_audit] Initializing SQLite cache at {db_path}")
    logger.info("Initializing SQLite cache at %s", db_path)
    try:
        store = SessionTimeStore(str(db_path), verbose=args.verbose)
    except sqlite3.OperationalError as exc:
        print(f"[xnat_audit] SQLite initialization failed: {exc}")
        logger.exception("SQLite initialization failed for %s", db_path)
        print("[xnat_audit] Close other processes using the database and retry, or remove the stale DB file if appropriate.")
        return 1

    if not settings.xnat_url:
        print("[xnat_audit] XNAT URL is not configured, so the app cannot query XNAT yet.")
        logger.warning("XNAT URL is not configured")
        return 0

    print(f"[xnat_audit] Connecting to XNAT at {settings.xnat_url}")
    logger.info("Connecting to XNAT at %s", settings.xnat_url)
    client = XNATClient(settings.xnat_url)
    try:
        client.connect()
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        print(f"[xnat_audit] XNAT connection failed: {exc}")
        logger.exception("XNAT connection failed")
        print("[xnat_audit] Ensure pyxnat is installed and your .netrc credentials are available for the configured host.")
        return 0

    print("[xnat_audit] Querying archive and prearchive sessions")
    logger.info("Querying archive and prearchive sessions")
    processed_sessions = ingest_sessions(client, store, target_date, target_date)
    print(f"[xnat_audit] Completed ingestion; processed {len(processed_sessions)} session(s)")
    logger.info("Completed ingestion; processed %d session(s)", len(processed_sessions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
