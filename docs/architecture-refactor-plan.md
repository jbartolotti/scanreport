# XNAT audit architecture refactor plan

## Goal

Split the current single workflow into two separate responsibilities:

1. Cache refresh / ingestion
2. Report generation

The cache workflow should only use lookback days and must never depend on report dates. The reporting workflow should only use report dates/weeks and must never query XNAT.

---

## Proposed directory structure

```text
xnat_audit/
  cli/
    __init__.py
    main.py
  config/
  ingestion/
    __init__.py
    client.py
    archive.py
    prearchive.py
    refresh.py
    stats.py
  normalization/
  reporting/
    __init__.py
    report.py
    calendar.py
    html.py
    templates/
  storage/
    __init__.py
    sqlite_store.py
  models/
```

### Responsibility split

- ingestion/: XNAT access, normalization, cache refresh, timing metadata
- reporting/: SQLite reads, report shaping, HTML/calendar generation

---

## Files requiring modification

### Core workflow entrypoints
- [xnat_audit/cli/main.py](xnat_audit/cli/main.py)
  - split into `refresh` and `report` subcommands
  - remove date-based ingestion behavior from the CLI flow

### Ingestion layer
- [xnat_audit/ingestion/client.py](xnat_audit/ingestion/client.py)
  - keep XNAT transport logic here
  - remove report-date semantics from ingestion helpers
- [xnat_audit/ingestion/__init__.py](xnat_audit/ingestion/__init__.py)
  - export `refresh_cache()` and `ingest_recent_sessions()`
- [xnat_audit/ingestion/refresh.py](xnat_audit/ingestion/refresh.py)
  - new module for the ingestion entrypoint

### Reporting layer
- [xnat_audit/reporting/__init__.py](xnat_audit/reporting/__init__.py)
  - export `generate_report()`
- [xnat_audit/reporting/report.py](xnat_audit/reporting/report.py)
  - new module for report generation orchestration
- [xnat_audit/reporting/calendar.py](xnat_audit/reporting/calendar.py)
  - keep week/day shaping logic here
- [xnat_audit/reporting/html.py](xnat_audit/reporting/html.py)
  - keep rendering logic here

### Storage layer
- [xnat_audit/storage/sqlite_store.py](xnat_audit/storage/sqlite_store.py)
  - rename or generalize the store from timing-cache-only to session-registry

### Tests
- [tests/test_ingestion.py](tests/test_ingestion.py)
- [tests/test_config_cli.py](tests/test_config_cli.py)
  - update for new `refresh` / `report` CLI behavior

---

## Refactored function signatures

### Ingestion

```python
from datetime import date
from typing import Any


def refresh_cache(
    *,
    client: Any,
    store: Any,
    lookback_days: int,
) -> dict[str, int]:
    ...


def ingest_recent_sessions(
    *,
    client: Any,
    store: Any,
    lookback_days: int,
) -> dict[str, int]:
    ...


def ingest_archive_sessions(
    *,
    client: Any,
    store: Any,
    lookback_days: int,
) -> dict[str, int]:
    ...


def ingest_prearchive_sessions(
    *,
    client: Any,
    store: Any,
    lookback_days: int,
) -> dict[str, int]:
    ...
```

### Reporting

```python
from datetime import date
from typing import Any


def generate_report(
    *,
    store: Any,
    report_date: date | None = None,
    report_week: date | None = None,
) -> dict[str, Any]:
    ...


def load_sessions_for_report(
    *,
    store: Any,
    report_date: date | None = None,
    report_week: date | None = None,
) -> list[Any]:
    ...
```

### Store API

```python
class SessionRegistryStore:
    def initialize(self) -> None: ...
    def upsert(self, record: dict[str, Any]) -> None: ...
    def get(self, session_id: str) -> dict[str, Any] | None: ...
    def list_for_date(self, report_date: date) -> list[dict[str, Any]]: ...
    def list_for_week(self, week_start: date) -> list[dict[str, Any]]: ...
    def has_changed(self, session_id: str, signature: str) -> bool: ...
    def mark_checked(self, session_id: str) -> None: ...
```

---

## Migration plan from the current workflow

### Phase 1: Introduce the new boundaries
- Keep existing ingestion behavior intact, but wrap it behind `refresh_cache()`.
- Introduce `generate_report()` in the reporting package.
- Keep the old `ingest_sessions()` function as a compatibility wrapper for now.

### Phase 2: Move date semantics
- Remove `start_date` and `end_date` from ingestion entrypoints.
- Replace them with `lookback_days` only.
- Ensure reporting code never calls XNAT and only reads SQLite.

### Phase 3: Split the CLI
- `python -m xnat_audit refresh`
  - runs ingestion only
  - updates SQLite cache
- `python -m xnat_audit report --date 2026-06-29`
  - reads SQLite only
  - builds report structures

### Phase 4: Deprecate the old single-flow behavior
- Remove or freeze the old combined CLI path.
- Update documentation and tests to use the new entrypoints.

---

## SQLite schema changes

The current `session_times` table is a timing cache. The refactor should evolve it into a session registry.

### Recommended change

Create a new table named `sessions` with the following columns:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT,
    state TEXT,
    start_time TEXT,
    end_time TEXT,
    dicom_count INTEGER,
    scan_profile TEXT,
    signature TEXT,
    last_checked TEXT
);
```

### Compatibility approach

To reduce churn during migration, either:

1. keep the existing `session_times` table and add a compatibility view, or
2. rename the table to `sessions` and provide a compatibility view named `session_times`.

### Why this matters

The new schema better reflects the intended role of SQLite:

- local normalized registry of discovered sessions
- source of truth for report generation
- not a transient timing cache

---

## Date-handling rules

### Cache refresh
- uses `lookback_days` only
- example: `lookback_days = 30` means refresh sessions from the last 30 days

### Report generation
- uses `report_date` or `report_week` only
- report generation must never query XNAT

This removes the current confusion between:
- `start_date`
- `end_date`
- `target_date`
- `lookback_days`

---

## Recommended implementation order

1. introduce `refresh_cache()` and `generate_report()` entrypoints
2. move the current ingestion loop into the ingestion package
3. move report shaping into the reporting package
4. split CLI into `refresh` and `report`
5. migrate SQLite schema to `sessions`
