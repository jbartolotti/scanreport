# xnat-audit

xnat-audit is a Python package scaffold for auditing MRI scan data stored in an XNAT repository and generating daily or weekly reports. The current implementation focuses on clean architecture, modularity, and extensibility rather than complete business logic.

## Purpose

The package is designed to help teams answer practical operational questions about incoming MRI data:
- Which sessions are present in the XNAT archive or prearchive?
- Are expected sequences present for each session?
- Are there anomalies such as missing sequences, duplicates, or abnormal DICOM counts?
- How should sessions be summarized in a calendar-style report for review?

## Key features

- Read-only XNAT ingestion via a dedicated client abstraction
- Normalization of raw XNAT payloads into internal domain models
- Profile learning for typical scan expectations per project
- Reconciliation engine for anomaly detection
- Scheduled-provider interface designed for future EPIC integration
- HTML reporting scaffold for weekly calendar-style output

## Architecture overview

The package is organized into focused modules:
- ingestion: XNAT client and query wrappers
- models: domain models for sessions, scans, profiles, and enums
- normalization: raw-data normalization and sequence naming rules
- reconciliation: anomaly detection logic and configurable rules
- scheduling: abstract provider and future EPIC implementation
- reporting: calendar data and HTML rendering
- storage: JSON snapshot persistence
- cli: command-line entrypoint
- config: configuration helpers

## Data flow

1. Raw session data is pulled from the XNAT archive and prearchive.
2. The data is normalized into internal models.
3. Historical sessions are used to build project-level scan profiles.
4. New sessions are compared against those profiles to detect anomalies.
5. Results can be stored as snapshots and rendered as HTML reports.

## Planned EPIC integration

Scheduling data is not yet reliable because iLab integration is not available. The package therefore uses a pluggable ScheduleProvider interface so that future EPIC integration can be added without changing the core audit workflow.

## Current limitations

- Scheduling information is intentionally placeholder-only.
- The package relies on XNAT state information for archive versus prearchive tracking.
- Sequence normalization is currently a minimal scaffold and will need domain-specific mapping later.

## Example usage

Run with an explicit config file:

```bash
python -m xnat_audit config.json --date 2026-06-29
```

If no config file is supplied, the CLI will look for a local config.json in the current working directory and use today’s date by default:

```bash
python -m xnat_audit
```
