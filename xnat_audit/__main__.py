"""Module entrypoint for running the package as a module."""

from .cli.main import main


if __name__ == "__main__":
    raise SystemExit(main())
