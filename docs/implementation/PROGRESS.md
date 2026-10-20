# Implementation progress

**Current stage: STAGE_03=PASS**

## Stage 03 execution plan (2026-10-20)

Inspected Stage 03, architecture/test matrix and repository instructions, README, CLI,
ingestion archives, provider/runtime guards, contracts, legacy applicability and Day Three
services/tests. Baseline: clean branch feat/day-three-rag-questions; Day Three focused
tests 72 passed/1 opt-in skipped. Prior Stage 02 full suite 448 passed/1 skipped.
Documentation is now tracked (older ignored/no-commit statements below are historical).

Plan: (1) extend profile contracts compatibly; (2) implement bounded device-only archive
extraction, exact quotes, product scope, conflicts and manual fallback; (3) persist
immutable profile revisions and reviewed edits with optimistic concurrency, add additive
CLI preview/review/import; (4) add synthetic offline and failure tests, run focused then
full suite, document results and commit only after gates pass. Streamlit profile editing
belongs to the later reviewer workspace stage; current conversations remain unchanged.

Risks: literal quotations establish provenance, not semantic correctness. All extracted
facts remain pending review; no autonomous classification or conformity conclusions.
No real corpus/model/network calls, downloads or dependency installation planned.
Next action: implement contracts, service and tests together.

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

## Stage 03 measured progress (2026-10-20)

- Initial synthetic profile suite: 26 passed/1 failed. Missing attributes in an empty model
  object were initially accepted by a default; made the output inventory explicitly required.
- Compatibility suite: 115 passed in 63.35s (profile/foundations/orchestrator/conversations).
- Expanded profile suite: 30 passed/1 failed due to the new test referring to a nonexistent
  settings log_path; corrected to existing database_path.with_suffix('.jsonl').
- Next profile suite: 31 passed in 10.69s.
- An early full suite was interrupted during final review; NOT a completed gate. Final review
  added explicit unknown-label abstention, consistent persisted CLI revision output, and
  profile-stage metadata-only telemetry. No existing tests changed or weakened.
- Final focused profile + foundations: 98 passed in 7.92s, including 33 new profile cases.
- Final complete suite: RUNNING using
  `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-stage03-release-full`.
- profile --help, compileall and intermediate diff whitespace checks: PASS.

No actual provider network/model calls, user-corpus extraction, dependencies or downloads.
Real model/OCR/browser integration NOT RUN. Next: full suite result, privacy/diff checks,
final documentation and authorized commit. Stage 04 is not started.

Final review also added a conservative model field-topic check: even a genuine quotation
cannot populate an unrelated field merely because its offsets match. Unsupported topics
and explicit unknown quotations abstain; this is not a semantic entailment guarantee.
The release-full run was interrupted for this refinement (NOT a completed test gate).
Current exact code: profile + foundations 98 passed in 8.29s. Definitive full command:
`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-stage03-complete`.

Native-format review found the Stage 02 parser marks every PDF with a general
pdf_tables_not_structurally_verified diagnostic. Changed profile filtering to reject
known blocking extraction/OCR flags while preserving readable native prose and its
source_layout_unverified warning. Added PDF, DOCX and Markdown profile roundtrip tests,
including exact physical PDF page. The previous complete run was interrupted for this
fix and is NOT a gate. Final focused native-format/profile/foundation command:
`.\.venv\Scripts\python.exe -m pytest -q tests/test_device_profile.py tests/test_foundations.py -p no:cacheprovider --basetemp reports/test-temp-stage03-native-formats`
PASS: 101 passed in 8.82s, including 36 new profile cases.
Final full command (current code, pending):
`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-stage03-gate`.

## Final Stage 03 gate - STAGE_03=PASS (2026-10-20)

| Check | Exact result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-stage03-gate` | PASS: 556 passed, 2 skipped in 270.41s (4m30s), no warnings |
| `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_profile.py tests/test_foundations.py -p no:cacheprovider --basetemp reports/test-temp-stage03-native-formats` | PASS: 101 passed in 8.82s; 36 new profile cases |
| Earlier profile/foundations/orchestrator/conversations | PASS: 115 passed in 63.35s before final additions |
| `.\.venv\Scripts\python.exe main.py --help` and `main.py profile --help` | PASS: all 15 earlier commands retained, additive profile command |
| `.\.venv\Scripts\python.exe -m compileall -q main.py mdr_rag tests/test_device_profile.py` | PASS on final source |
| `git diff --check`, staged whitespace and scoped-file review | PASS; only eight intentional files; no secrets or real source data included |
| Ignore checks for .env, state/device_profiles and reports | PASS |
| Live Ollama / real cross-encoder / OCR / manual browser | NOT RUN: two existing opt-in model checks skipped; no live services invoked |
| Ruff / mypy / Black | NOT RUN: not installed, no configured toolchain found; no installation performed |

Implementation files:
- mdr_rag/device_profile.py: bounded device-only manifest preview, deterministic labelled
  fields, opt-in Role A provider, one budget-bound schema repair, exact quote/offset/topic
  validation, subject isolation, conflict merge, manual fallback/questions, legacy import,
  metadata-only profile events, immutable revision storage and audited review operations.
- mdr_rag/contracts.py: additive origin/review_state/conflicts and self_declared status;
  existing contracts/consumers remain readable.
- main.py: additive profile extract/show/import/review commands; persisted responses load
  the exact saved revision. No changes to existing command contracts.
- mdr_rag/telemetry.py: fixed profile-stage vocabulary; no arbitrary user strings logged.
- tests/test_device_profile.py: 36 synthetic non-regulatory offline cases; no pre-existing
  test was changed, removed or weakened.
- README.md and docs/implementation/{PROGRESS,DECISIONS}.md: commands, semantics,
  measured gates, compatibility, privacy, limitations and rollback.

Gate coverage: exact structured native PDF/DOCX/TXT/MD evidence and physical PDF page;
unknown/null and explicit unknown-label abstention; negative/modal/bilingual text; mutually
contradictory purposes; immutable confirmed/overridden/rejected states with editor/reason,
no-source manual fallback, competitor/multi-product/YAML/HTML subject rejection, invalid or
truncated schema with bounded repair, offline/missing model/timeouts/call budget, forged
quotes/IDs/topic mismatches, scan/no-text, wrong collection/project, five-run idempotence,
versioned source conflicts, Windows filenames, tampered originals/revisions, stale updates,
forged manual/evidence changes, failed head publication and redacted event output.

Compatibility/deviations:
- No automatic user-data or SQL migration; legacy JSON is imported explicitly and retained
  as untrusted self-declared data. New states use project-scoped content-addressed JSON;
  Stage 01 SQL ledger and old flat review/applicability input stay unchanged.
- Typed ProfileDraft/ProfileField enrich the prior generic contracts without rewriting
  existing consumers. Reviewed profiles are not silently exported to legacy applicability.
- Streamlit profile editing is deferred to the later reviewer workspace exactly as the
  Stage 03 specification allows; current Day Three UI/CLI workflows pass regressions.
- Strict same-span product subject and field-topic cues sacrifice recall, especially across
  pages, tables and free-form/bilingual descriptions. Native PDF prose is retained with a
  layout warning; damaged/unreadable/OCR/nested-table evidence abstains. Exact citations
  and topic cues are not semantic entailment, completeness, expert review or certification.
- Automatic classification/category remains unknown; manual edits are explicitly attributed.
  Review does not rewrite source evidence. Re-extraction explicitly resets review on a new
  child revision; prior reviewed history stays immutable and available.
- Locking/expected heads prevent ordinary concurrent lost updates. Revision/head writes are
  atomic per file, not a cross-store transaction; orphan revisions can remain after failure.
  No automatic cleanup, encryption, authentication or secure deletion is introduced. Audit
  metadata and device values stay sensitive on local disk. Telemetry IO failure cannot
  replace a successful extraction or mask its original exception.

Costs and latency: 0 real network/model/API calls, $0 cloud spend, no dependencies or model
weights installed, no real user dossier parsed or index rebuilt. Native parsing/local IO
and mocked guarded Ollama calls were exercised. Default extraction requires no inference;
explicit model path makes at most two logical requests (initial + schema repair), with
Stage 01 bounded transient retries and shared run limits. 270.41s is test-suite duration,
not device-processing/model performance. No accuracy/latency benchmark claim is made.

Rollback: revert the Stage 03 Git commit after reviewing dependent work. Preserve all user
files, ingestion originals, existing indexes, assessment history and ignored profile states.
The prior application can ignore the new profile directory; no reverse SQL/data migration
or deletion is required. Export new profile revisions before using an older application
which has no profile command. Implementation and docs are committed on the explicitly
requested feature branch; nothing is pushed or deployed.

STAGE_03=PASS. Next stage: docs/day_two_prompts/stages/04_REGULATORY_REGISTRY.md.
STOP: Stage 04 is not started.
