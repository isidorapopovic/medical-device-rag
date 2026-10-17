# Implementation progress

**Current stage: STAGE_02=PASS**

**STAGE_01=PASS** - final measured result below supersedes intermediate statuses.

## Stage 01 - PASS (2026-10-17)

Baseline inspected: root README/main/Streamlit, day_two_prompts AGENTS and complete Stage 01/reference specifications, schemas/config/search, JSON StateStore/SourceBuffer, review checkpoints, configuration/CLI/reranking tests, requirements and .env.example. Prior baseline: 318 passed / 1 opt-in integration skipped; no services required. Current branch chore/day-two-stage-00-baseline; unrelated `how HEAD` remains untouched. docs/ remains intentionally ignored.

Plan:
1. Add validated settings, typed provenance/run contracts and explicit legacy adapters.
2. Add transactional, migrated SQLite run ledger; preserve canonical JSON assessments.
3. Add redacted telemetry, provider interfaces/fakes, bounded retries/timeouts/cancellation/circuit breaker and pre-call budget reservation/reconciliation. Integrate local call sites through compatibility facades.
4. Test focused failure paths and migration/roundtrip/privacy gates, then full offline suite; inspect diff and document measured status.

No commit/push, cloud requests, dependency installation, model downloads, legal fetch or index rebuild is authorized by this stage. Next action: implement foundations and tests alongside adapters.

## Stage 01 test progress

- Focused v1: 74 passed (foundations + existing config and Stage 00 tests), 6.50s.
- Existing adapters: 38 passed, 1 optional real-model smoke skipped, 17.83s.
- Expanded focused v2: 84 passed / 1 failed, 8.73s. Failure was a new assertion treating HTTPX UseClientDefault as a boolean; corrected to assert the effective client's follow_redirects property is false. No existing test was weakened or deleted.
- Combined focused adapters: 123 passed, 1 optional real-model skipped, 15.63s; one pytest cache permission warning, no test failure.
- Latest foundations-only suite: 64 passed, 4.29s (includes SDK HTTP transport mocked before network, transient/permanent errors, complete .env.example parsing, malicious model override rejection and durable crash reservations).
- Full suite `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage01-full`: RUNNING; final result pending.
- compileall and git diff --check: PASS at intermediate check. ruff/mypy/black not installed; no configured lint/type check found, so NOT RUN; no dependencies installed.

Risks: conservative token estimates may block earlier than true token counts; large runs must explicitly size budgets. HTTP phase timeouts/native CPU scoring have cooperative deadline limits. JSON assessment store remains canonical; no all-document SQL migration. Legacy direct ConnectionError API remains, but CLI/logging sanitizes it. Each resume invocation gets a new budget (not a lifetime project quota). No real model integration benchmark or legal registry verification is claimed.

Next action: finish full offline suite, inspect diff and privacy boundaries, update final gate status. Stage 02 is not started.

## Final validation in progress (2026-10-17)

First full suite: `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage01-full` — FAIL, 1 failed / 381 passed / 1 skipped in 237.32s. The unchanged legacy reranker test injects a SimpleNamespace Ollama module without Client/ResponseError; the new adapter initially assumed those SDK attributes. Fixed adapter to respect that explicit minimal-module fake. No existing test changed.

Regression after fix and final typed-context refinement: `.\.venv\Scripts\python.exe -m pytest -q tests/test_foundations.py tests/test_evaluation.py tests/test_config.py --basetemp reports/test-temp-stage01-final-focused -o cache_dir=reports/pytest-cache-stage01` — PASS, 80 passed in 11.01s. Foundations now contain 65 cases.

Final complete suite: `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage01-final-full -o cache_dir=reports/pytest-cache-stage01` — RUNNING. Cache moved to ignored reports to avoid Windows .pytest_cache permission warnings; no tests skipped to work around failures.

CLI `main.py --help`: PASS with all 13 commands. compileall and git diff --check: PASS after final implementation edits. Git ignore checks: docs/implementation, SQLite ledger and JSON logs remain ignored. No existing test files changed. New tests use synthetic text, fake secrets and mocked HTTP send; actual API/model calls = 0, cloud spend = $0. No dependencies installed, no real model downloaded or invoked, no user source contents inspected/transmitted and no index rebuilt.

Additional preserved risk: the existing `index` implementation deletes/recreates its Chroma collection before embedding completes. A budget or provider failure can still leave a partial replacement. This stage preserves that command's existing destructive semantics rather than introducing an untested index migration; do not run it merely as a smoke check. A staged index activation belongs to the ingestion/retrieval work. Legacy assessment snapshots are retained independently.

## Final gate — STAGE_01=PASS (2026-10-17)

| Check | Exact result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage01-final-full -o cache_dir=reports/pytest-cache-stage01` | PASS: 383 passed, 1 skipped, 1 warning in 235.91s (3m55s) |
| Final focused foundations/evaluation/config command above | PASS: 80 passed, 11.01s; includes 65 new foundations tests |
| `.\.venv\Scripts\python.exe main.py --help` | PASS: 13 existing commands and flags preserved |
| `.\.venv\Scripts\python.exe -m compileall -q main.py streamlit_app.py mdr_rag tests/test_foundations.py` | PASS |
| `git diff --check` + owned-file whitespace review | PASS; new files additionally checked because git diff omits untracked files |
| Real Ollama / real CPU cross-encoder / cloud / UI browser | NOT RUN: optional services/weights/opt-in not exercised; existing opt-in real_model test skipped |
| Formatting/lint/type tools | NOT RUN: no configured tools or installed ruff/mypy/black; no tool installation performed |

The remaining warning is PytestCacheWarning (WinError 5) writing nodeids, even after relocating cache under reports. It does not fail tests or affect assertions. A diagnostic rerun can disable the nonessential cache plugin with `-p no:cacheprovider`; no further suite repetition is required for a cache-only warning.

Implemented files:
- New `mdr_rag/settings.py`, `contracts.py`, `errors.py`, `run_store.py`, `runtime.py`, `providers.py`, `telemetry.py`.
- Adapted `main.py`, `mdr_rag/pipeline.py`, `search.py`, `reranking.py`, `evaluation.py`.
- New `tests/test_foundations.py` (65 cases). Existing tests untouched.
- Updated `.env.example`, README.md and local docs/implementation/PROGRESS.md + DECISIONS.md. Requirements/.env/.gitignore/Streamlit/legacy rag.py unchanged.

Gate coverage: default/local and cloud rejection; explicit opt-in without cloud client; no import-time SDK client; UTC/hash/Unicode/reference/version/schema validation; legacy JSON adapter/StateStore regressions; foreign keys, unique IDs, roundtrip, v1-to-v2 upgrade, newer-schema refusal, transaction/DDL rollback, locked DB and simulated disk-full errors; pre-call calls/input/output/prompt/USD limits, measured reconciliation and crash charges; bounded transient retries, permanent-error no retry, circuit breaker, cancellation/deadline/discarded late response; SDK transport timeout/loopback/no redirects/output cap; redaction and run correlation; injected malicious model override stays untrusted; batch splitting preserves text. No benchmark accuracy or legal/currentness claim made.

Compatibility/deviations: SQL is canonical only for new run usage, while legacy assessment JSON remains canonical and migration-tested. Legacy section errors remain failed for resume compatibility; invocation ledger records blocked. Budgets reset on a new invocation/resume, not per retry and not a lifetime project quota. Cancellations/timeouts are cooperative; native CPU calls are not hard-killed. Conservative estimates may exhaust earlier than true counts. Existing index replacement can still be partial on failure; this stage did not execute it.

Cost and latency: 0 real model/network/API calls, $0 cloud spend; final deterministic suite 235.91s. New runtime adds local transactional reserve/reconcile and metadata-log IO per operation; no measured model-latency claim. SQLite and log files contain run metadata/counters only; persisted source text remains in existing private evidence snapshots, not new logs.

Rollback: review the diff, restore only Stage 01 edits in `.env.example`, README.md, main.py, mdr_rag/evaluation.py, pipeline.py, search.py and reranking.py; remove only the seven new foundation modules and tests/test_foundations.py if desired. Keep user documents, indexes, legacy JSON snapshots, unrelated `how HEAD`, and this audit history. The ignored runtime database/log can remain unused after code rollback; no reverse database migration or data deletion is necessary. No commit/push was made.

Next stage: `docs/day_two_prompts/stages/02_DOCUMENT_INGESTION_AND_PROVENANCE.md`. STOP: Stage 02 has not started.

# Stage 02 - PASS (2026-10-17)

Inspected full Stage 02/AGENTS/architecture/test-matrix specifications, README, main/Streamlit, core loaders/upload helper, SourceBuffer and assessment schemas, Stage 01 settings/ledger, dependency list and loader/citation/index tests. Baseline: Stage 01 full suite 383 passed, 1 opt-in real-model skipped; code committed at a916302, clean working tree before this stage. docs/ remains intentionally local/ignored.

Plan:
1. Implement bounded PDF/DOCX/TXT/MD parser adapters with physical-page or structural block locations, single versioned normalization and raw-offset maps, diagnostics and explicitly opt-in local OCR interface.
2. Add per-project, content-addressed originals and immutable extraction manifests; idempotent uploads, explicit document versions, safe Windows filename/path handling, atomic publication and exact-source context resolution.
3. Integrate loaders, ingestion CLI/service, Streamlit uploads, snapshot provenance and changed-vector reuse/safe index preparation. Preserve legacy CLI/report contracts and low-level upload helper behavior through adapters.
4. Generate only synthetic fixtures; test malformed/scan/encrypted/Unicode/table/zip/size/duplicate/project-isolation/injection/IO-failure paths. Run focused checks then full offline suite; document actual gate, limitations and rollback. No commit/push, real model invocation, downloads, legal fetch or actual user index rebuild.

Decisions: Keep canonical ingestion artifacts in project-scoped JSON/content blobs under ignored state/ingestion; do not duplicate assessment JSON or change Stage 01 ledger migrations. Preserve old source snapshots unchanged. New indexed records carry extraction-manifest references; historical legacy citations remain verifiable against their old snapshots but do not acquire invented original-file provenance.

## Stage 02 measured progress

- Loader/source-buffer/foundation adapters: 131 passed, 24.99s.
- Initial new ingestion suite: 44 passed, 3.66s; two Pydantic instance-model_fields deprecations identified and fixed by querying the class.
- Ingestion + legacy upload/CLI/source snapshots: 118 passed, 23.66s.
- Expanded foundations/ingestion compatibility: 188 passed, 26.46s.
- Expanded suite including real offline Chroma and guarded publication: 193 passed, 23.64s.
- Post-path-confinement integration: 128 passed, 24.82s.
- Additional unreadable-glyph gate: ingestion suite 63 passed, 7.98s.
- Full suite initially launched while final readability/Unicode-path checks were under review: still running; result will be recorded as an intermediate run rather than attributed to the final code.
- Final Unicode source routing/requirement-extraction compatibility check is running. Next: final full suite on the completed implementation, then gate verdict.

No existing tests changed or weakened. Test corpus contains generated, clearly synthetic PDFs/DOCX/text only. A real local temporary Chroma database was tested using fake embeddings with socket connections blocked and Chroma telemetry disabled. No actual model/remote calls or real OCR engine run, no external source fetch, no new dependency installation and no user index rebuild. Cloud spend $0. CLI help and compileall passed; git diff --check passed. Docs remain local/ignored by the user's existing policy.

Late review refinements: replacement-glyph-dominated pages retain diagnostic raw extraction but generate no citable spans. Canonically equivalent copied filenames resolve to the original filesystem path without renaming source files, and ambiguous normalized/casefold names are rejected. Native table/header limitations are explicit, not omitted from provenance views.

## Stage 02 final verification in progress

- Intermediate full run: `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage02-full -p no:cacheprovider` — PASS, 445 passed / 1 skipped in 424.42s. This run predates final glyph/Unicode routing additions.
- Final compatibility expansion: 147 passed / 1 failed in 95.25s. The unchanged six-role CLI test injects a PDF opener for a missing toy file; new alias routing initially rejected the path too early. Fixed the adapter's explicit allow_missing mode so the existing opener retains responsibility for missing-file behavior, while archive/manifest verification remains strict.
- Targeted fix and current ingestion suite: `.\.venv\Scripts\python.exe -m pytest -q tests/test_ingestion.py tests/test_orchestrator.py::test_complete_six_role_cli_workflow_without_apis --basetemp reports/test-temp-stage02-resolver-fix -p no:cacheprovider` — PASS, 66 passed, 15.47s. Includes 65 new ingestion cases and the original failing compatibility case.
- Final full suite on completed code: `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage02-final-full -p no:cacheprovider` — RUNNING.
- CLI help: PASS; all 13 old commands retained, with ingest and source-view added. index --force-reembed is explicit opt-in.
- compileall / git diff --check / all 15 owned-file whitespace review: PASS. Existing test files unchanged. Git ignore checks pass for state archives, the alternate documents/.ingestion store, test outputs and local documentation.
- Formatting/lint/type checks: NOT RUN (no configured tools or installed ruff/mypy/black). No new dependencies installed.

Next action: record the final full result and verdict. Stage 03 is not started. No commit or push performed.

# Final Stage 02 gate - STAGE_02=PASS (2026-10-17)

| Check | Exact measured result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage02-final-full -p no:cacheprovider` | PASS: 448 passed, 1 skipped in 472.81s (7m52s); no warnings |
| Current ingestion cases + unchanged six-role CLI compatibility regression | PASS: 66 passed, 15.47s; includes all 65 new ingestion cases |
| Earlier expanded focused adapters/foundations | PASS: 193 passed, 23.64s (before final glyph/filename additions) |
| `.\.venv\Scripts\python.exe main.py --help` | PASS: 13 legacy commands preserved; ingest/source-view added |
| `.\.venv\Scripts\python.exe -m compileall -q main.py streamlit_app.py mdr_rag tests/test_ingestion.py` | PASS |
| `git diff --check` + whitespace review including untracked source/tests | PASS |
| Real local Chroma index preparation/swap/cache test with fake embeddings and blocked sockets | PASS (part of deterministic suite) |
| Real Ollama / real CPU cross-encoder / real OCR / browser-driven Streamlit | NOT RUN: no live model/engine opt-in, cached-weight assumption or browser integration claim |
| Formatting/lint/type checks | NOT RUN: no configured/installed ruff, mypy or black; no tool installation |

The single skip is the existing opt-in real CPU cross-encoder smoke. It is NOT RUN, not a passed integration test. The earlier resolver compatibility failure was investigated and fixed in the adapter, without changing existing test expectations. The final full suite supersedes intermediate results.

## Actual changes

- New document_parsers.py: bounded MIME/ZIP/XML/PDF/DOCX/text parsing; physical PDF pages, native page text, paragraph/table/cell order, Markdown headings and TXT/MD line/block offsets; versioned NFC/whitespace policy and exact raw envelopes; diagnostics for failed/empty/encrypted/damaged/rotated/scanned/degraded extraction; opt-in local OCR interface/backend with unverified labels.
- New ingestion.py: project/collection-scoped logical document UUIDs and versions; SHA-addressed original bytes and immutable extraction manifests; atomic heads, idempotent ingestion, original integrity checks and exact citation/context views; metadata-only JSON events.
- core.py and requirement_analyst.py: parser compatibility facade, archived index input manifests, Unicode/Windows source-label routing and ambiguous-name protection; preserve existing PDF opener behavior and source selection contracts.
- document_ui.py and streamlit_app.py: safe Windows paths/size limits, serialized atomic legacy no-overwrite helper, validated archive-first UI publication preserving old bytes, upload/preview/download functionality and extraction warnings.
- source_buffer.py: schema-2 archive references and snapshot-to-original resolution, while preserving schema-1 shapes/IDs and immutable history.
- search.py and pipeline.py: changed-vector reuse with model/project identity, explicit force-reembed, full staging before collection replacement, recovery backups, promotion rollback and cache clearing; atomic JSON output and original-manifest integrity checks before reuse.
- main.py: additive ingest/source-view commands and index --force-reembed. settings.py keeps OCR off by default while permitting explicit opt-in; telemetry.py adds fixed OCR/ingestion stages.
- tests/test_ingestion.py: 65 deterministic cases; every pre-existing test file unchanged. README and local implementation decisions/progress updated. .gitignore adds only /documents/.ingestion/ for alternate isolated source roots. Existing .env, requirements, rag.py, user source files and user vector index were not modified.

## Compatibility, limitations and cost

All legacy deterministic tests pass. No source/index/report migration runs automatically. Legacy originals that were never archived are not recoverable from invented metadata; their old source snapshots remain explicitly legacy. New archived passages require the current schema-2-capable reader; keep it or export reports before rolling code back after producing new histories.

PDF table layout is not structurally verified; omitted DOCX components/nested tables are diagnosed. OCR accuracy is unmeasured, local English backend support is optional and output remains unverified; archived OCR text is not silently substituted into native legal indexing. Parser limits and cooperative native calls are not a process-isolation security guarantee. XML entities, archive expansion/member limits, scan/glyph failures, traversal, symlink/junction paths and injected document instructions have deterministic rejection/retention tests.

Original/manifest/head publication is staged and atomic per artifact. Failed publication can leave unreachable immutable blobs, never a partially committed head. Working-copy publication and archive publication are separate: a failed mirror update can be retried idempotently. Chroma collection activation and global index-manifest publication are separate operations, not one crash-atomic transaction; an error requires manual investigation with preserved backup collections. Backups are not auto-deleted and consume local disk. Concurrent index rebuild processes are not a distributed transaction.

Cost: 0 real model/API/network calls, $0 cloud spend, no downloads or dependency installation. Real temporary local Chroma and native synthetic document parsing were exercised. Final full-suite time is 472.81s, not model/dossier processing performance. Archiving, hashing and offset validation add local CPU/IO; unchanged extraction/vector reuse avoids unnecessary inference. Test artifacts and archival/runtime data remain ignored/private. No actual user corpus was parsed for this implementation, and no actual user index was rebuilt.

## Rollback and next action

After reviewing the diff, restore only Stage 02 edits in .gitignore, README.md, main.py, streamlit_app.py and modified mdr_rag adapters to the Stage 01 baseline a916302; remove only the new document_parsers.py, ingestion.py and tests/test_ingestion.py if rolling back code. Do not delete source dossiers, state archives, reports, old snapshots or backup collections. Preserve local audit notes and unrelated files. New schema-2 histories need the current reader or prior exports. Restore index metadata/active backup only after explicit inspection; no data rollback was performed here.

STAGE_02=PASS. Next stage: docs/day_two_prompts/stages/03_DEVICE_PROFILE_AND_REVIEW.md. STOP: Stage 03 has not started. No commit or push made.
