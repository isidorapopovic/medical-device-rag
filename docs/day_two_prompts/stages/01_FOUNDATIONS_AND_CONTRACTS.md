# Stage 01 — Foundations, typed contracts, logging and cost guards

## Goal
Add reusable models/infrastructure without changing user-visible answers.

## Implementation
1. Create or extend typed schemas (`Document`, `SourceSpan`, `RegulationEdition`, `Requirement`, `DeviceProfile`, `Finding`, `AssessmentRun`) from `reference/ARCHITECTURE_AND_ACCEPTANCE.md`; Pydantic strict enums and validators for ISO timestamps, SHA256, normalized Unicode, IDs and evidence references. Preserve legacy serialization via adapters.
2. Add central validated settings read from existing `.env` + environment; config dump must redact keys and secrets. Keep Ollama default; block cloud until opt-in. Provider interfaces with fake implementations for testing; no API client instantiated at import time.
3. Implement local transactional SQLite (or adapt existing persistence) with migration version table, foreign keys, unique constraints, WAL where supported and migration rollback. Prefer one project database; not a second competing shadow state.
4. Implement JSON structured logs, run IDs, elapsed time and error taxonomy (`ValidationError`, `ParsingError`, `MissingModel`, `TransientModelError`, `BudgetExceeded`, `CitationError`, `MissingEvidence`); logger must never include file contents or raw prompts.
5. Implement budgets for calls, elapsed wall time, estimated/measured tokens and optional USD; reserve budget *before* each call, reconcile measured usage after, fail-closed when exceeded. Defaults described in architecture doc; make model-specific token counting optional. Prevent unbounded chain retries.
6. Unit test correlation IDs, timeout behavior, cancellation, error mappings and schema migrations. No print-based secret leakage.

## Tests and fallbacks
- Invalid enums, nulls, duplicate IDs, non-UTC dates, malformed Unicode, huge text, invalid config numbers, missing Ollama, SQLite locked database, disk full via mocked IO, write rollback, existing legacy JSON parsing.
- On model outage retain saved state and set `blocked`, never return fabricated finding. On missing cloud credentials: config error; do not auto-fallback from local to cloud.

## Gate
100% of schema/transaction tests; legacy smoke tests unchanged; deterministic offline suite green; logs redaction tested with fake secrets.
