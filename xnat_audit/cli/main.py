"""Console entrypoint for the audit package."""

from __future__ import annotations

import argparse
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="python -m xnat_audit")
    parser.add_argument("--date", required=True, help="Target date for the audit run (YYYY-MM-DD)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # TODO: wire up ingestion, normalization, reconciliation, and reporting.
    print(f"Audit scaffold initialized for {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
