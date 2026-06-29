"""Console entrypoint for the audit package."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Sequence

from ..config.config import load_settings
from ..ingestion.client import XNATClient, ingest_sessions
from ..storage.sqlite_store import SessionTimeStore


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="python -m xnat_audit")
    parser.add_argument("config_path", nargs="?", default=None, help="Path to a JSON config file (defaults to ./config.json)")
    parser.add_argument("--date", default=None, help="Target date for the audit run (YYYY-MM-DD)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = args.config_path
    if config_path is None:
        config_path = Path("config.json")
        if not config_path.exists():
            config_path = None

    settings = load_settings(config_path)
    target_date = args.date or date.today().strftime("%Y-%m-%d")

    print(f"[xnat_audit] Starting audit run for {target_date}")
    if config_path is None:
        print("[xnat_audit] No config file supplied; using built-in defaults")
    else:
        print(f"[xnat_audit] Using config file: {config_path}")
    print(f"[xnat_audit] Loaded settings: xnat_url={settings.xnat_url or '<not set>'}, sqlite_db_path={settings.sqlite_db_path}")

    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[xnat_audit] Initializing SQLite cache at {db_path}")
    store = SessionTimeStore(str(db_path))

    if not settings.xnat_url:
        print("[xnat_audit] XNAT URL is not configured, so the app cannot query XNAT yet.")
        return 0

    print(f"[xnat_audit] Connecting to XNAT at {settings.xnat_url}")
    client = XNATClient(settings.xnat_url)
    try:
        client.connect()
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        print(f"[xnat_audit] XNAT connection failed: {exc}")
        print("[xnat_audit] Ensure pyxnat is installed and your .netrc credentials are available for the configured host.")
        return 0

    print("[xnat_audit] Querying archive and prearchive sessions")
    processed_sessions = ingest_sessions(client, store, target_date, target_date)
    print(f"[xnat_audit] Completed ingestion; processed {len(processed_sessions)} session(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
