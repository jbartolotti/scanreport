"""Console entrypoint for the audit package."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Sequence

from ..config.config import load_settings


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

    # TODO: wire up ingestion, normalization, reconciliation, and reporting.
    print(
        f"Audit scaffold initialized for {target_date} using config {config_path if config_path else 'defaults'}"
    )
    print(f"Loaded settings: xnat_url={settings.xnat_url or '<not set>'}, sqlite_db_path={settings.sqlite_db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
