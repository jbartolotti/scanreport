"""Console entrypoint for the audit package."""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from ..config.config import load_settings
from ..ingestion.client import XNATClient
from ..ingestion.refresh import refresh_cache
from ..reporting.report import generate_report
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
    """Create the CLI argument parser for refresh and report workflows."""
    parser = argparse.ArgumentParser(prog="python -m xnat_audit")
    parser.add_argument("command", nargs="?", choices=["refresh", "report"], default=None, help="Workflow to run")
    parser.add_argument("config_path", nargs="?", default=None, help="Path to a JSON config file (defaults to ./config.json)")
    parser.add_argument("--date", dest="report_date", default=None, help="Report date for the report workflow (YYYY-MM-DD)")
    parser.add_argument("--week", dest="report_week", default=None, help="Report week anchor for the report workflow (YYYY-MM-DD)")
    parser.add_argument("--lookback-days", type=int, default=None, help="Lookback window for cache refresh")
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
    target_date = date.today().strftime("%Y-%m-%d")
    command = args.command or ("report" if args.report_date or args.report_week else "refresh")

    print(f"[xnat_audit] Starting {command} workflow for {target_date}")
    logger.info("Starting %s workflow for %s", command, target_date)
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

    if command == "report":
        report_date = None
        report_week = None
        if args.report_date:
            try:
                report_date = datetime.strptime(args.report_date, "%Y-%m-%d").date()
            except ValueError:
                print(f"[xnat_audit] Invalid report date: {args.report_date}")
                return 1
        if args.report_week:
            try:
                report_week = datetime.strptime(args.report_week, "%Y-%m-%d").date()
            except ValueError:
                print(f"[xnat_audit] Invalid report week anchor: {args.report_week}")
                return 1
        report = generate_report(store=store, report_date=report_date, report_week=report_week)
        print(f"[xnat_audit] Generated report with {report['session_count']} session(s)")
        logger.info("Generated report with %d session(s)", report["session_count"])
        return 0

    if not settings.xnat_url:
        print("[xnat_audit] XNAT URL is not configured, so the app cannot query XNAT yet.")
        logger.warning("XNAT URL is not configured")
        return 0

    print(f"[xnat_audit] Connecting to XNAT at {settings.xnat_url}")
    logger.info("Connecting to XNAT at %s", settings.xnat_url)
    client = XNATClient(settings.xnat_url, lookback_days=args.lookback_days or settings.lookback_days)
    try:
        client.connect()
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        print(f"[xnat_audit] XNAT connection failed: {exc}")
        logger.exception("XNAT connection failed")
        print("[xnat_audit] Ensure pyxnat is installed and your .netrc credentials are available for the configured host.")
        return 0

    print("[xnat_audit] Refreshing archive and prearchive sessions")
    logger.info("Refreshing archive and prearchive sessions")
    refresh_stats = refresh_cache(client=client, store=store, lookback_days=args.lookback_days or settings.lookback_days)
    print(
        "[xnat_audit] Completed refresh; discovered={sessions_discovered}, processed={sessions_processed}, updated={sessions_updated}".format(
            **refresh_stats
        )
    )
    logger.info(
        "Completed refresh; discovered=%d processed=%d updated=%d",
        refresh_stats["sessions_discovered"],
        refresh_stats["sessions_processed"],
        refresh_stats["sessions_updated"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
