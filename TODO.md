# TODO

## Roadmap

### Phase 1: XNAT ingestion + anomaly detection
- Implement XNAT API calls for archive and prearchive data.
- Normalize session payloads into the internal domain models.
- Build sequence normalization mappings for scanner-specific naming variations.
- Implement anomaly detection logic for missing, unexpected, duplicate, and low-count scans.

### Phase 2: HTML calendar UI
- Create the weekly calendar layout with days as columns and times as rows.
- Add interactive HTML details for hover and click behavior.
- Build the reporting templates under the reporting/templates directory.

### Phase 3: snapshot history
- Add snapshot persistence for processed sessions.
- Support loading previous runs for comparison and trend analysis.

### Phase 4: EPIC integration
- Introduce a pluggable scheduling provider interface.
- Implement the EPIC provider behind the abstraction.
- Replace the current placeholder scheduling flow with real integrations.

## Concrete next tasks
- Implement the XNAT client authentication flow using .netrc.
- Build sequence normalization mappings for known scanner naming patterns.
- Implement anomaly detection logic in the reconciliation engine.
- Create the HTML template and render the weekly calendar.

## Tricky areas
- Prearchive versus archive handling can change the interpretation of data freshness.
- Sequence naming inconsistency across scanners and sites can lead to false positives.
- External scanner detection requires reliable metadata and may need a configurable heuristic.

## Design principles
- Separation of concerns between ingestion, normalization, reconciliation, scheduling, and reporting.
- Explainable anomaly detection with transparent rules and summaries.
- Config-driven rules so behavior can be adjusted without changing core logic.
