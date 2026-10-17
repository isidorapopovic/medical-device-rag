# Implementation progress

**Current stage: STAGE_06=PASS**

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


## Stage 03 implementation in progress (2026-10-17)

STAGE_03=IN_PROGRESS. Inspected Stage 03, prompt protocol, architecture/test matrix, Stage 01 contracts/runtime/providers, Stage 02 archive/parsers, CLI/UI and legacy profile consumers. Baseline branch feat/stage-01-foundations-telemetry; working tree initially clean. Existing Stage 02 focused audit: 65 ingestion + 93 compatibility tests passed.

Plan: (1) add conservative evidence-linked extraction and complete unknown field inventory; (2) add immutable optimistic review revisions, audited manual edits and explicit legacy import; (3) expose CLI/API preview/review and project-local confirmed-fact compatibility projection; (4) test source binding, conflicts, no-source/offline/budget/schema recovery, review/idempotency/fault behavior, run full offline suite, update notes and commit only Stage 03 changes on the current branch. Local model opt-in only; no downloads, legal fetch, cloud, corpus rebuild or Stage 04 work. Streamlit editor remains deferred per Stage 03 specification.

## Final Stage 03 gate (2026-10-17)

STAGE_03=PASS. Stage 04 has not started.

Actual implementation: additive DeviceAttribute evidence/origin/review/conflict fields in contracts.py; device_profile.py for bounded evidence-linked previews, conservative product separation, unknown/question handling, optional local structured generation, immutable revisions and audited optimistic/idempotent review; profile_cli.py plus four additive main.py commands; pipeline.py confirmed-only compatibility projection with unchanged legacy fallback; null-based synthetic example, README workflow, decisions and 57 new deterministic tests. Existing test files and dependencies are unchanged. Documentation is tracked since the user's preceding documentation commit.

Validation:
- Final focused: `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_profile.py -p no:cacheprovider` — PASS: 57 passed in 5.77s.
- Earlier profile/foundations/baseline/orchestrator compatibility run — PASS: 140 passed in 14.73s (before final 16 profile regressions were added).
- Intermediate full suite — PASS: 500 passed, 1 skipped in 112.79s. This run started before the final negation-value fix and five final regressions and is not the final-code gate.
- `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` — PASS: 505 passed, 1 skipped in 102.31s (1m42s); no warnings.
- `.\.venv\Scripts\python.exe -m compileall -q main.py mdr_rag tests/test_device_profile.py` — PASS. AST parsing of all changed Python modules — PASS.
- CLI main/profile-edit help — PASS: all 15 existing commands retained and four profile commands added.
- `git diff --check`, new-file whitespace, ignored profile-storage checks and sample JSON import — PASS. Sample import creates zero confirmed assertions.
- Ruff/Black/mypy — NOT RUN: not installed and no corresponding configured toolchain; no tools/dependencies installed.
- Real Ollama, real OCR, real CPU cross-encoder, browser UI — NOT RUN. The existing optional cross-encoder test is skipped, not counted as a passed integration. Streamlit profile editing is deferred per Stage 03.

Coverage includes unknown/missing fields, source hashes/offsets, explicit negative values, negation fragments and quote/value disagreement, conditional wording, cross-document conflicts, competitor/multi-product scope, bilingual labels, inert YAML/HTML instructions, malformed output with at most one budgeted repair, actual guarded-transport fakes, offline/timeout/cancellation/budget fallbacks, five repeated previews/publications, immutable original/revision retention, manual edit/confirm/reject, source-free audit origin, stale edits, conflicting idempotency keys, interrupted publication, legacy aliases/unmapped fields and direct API publication bypass rejection.

No source-derived fact is auto-confirmed. Only accepted/overridden values enter the legacy review projection; their revision hash invalidates existing dependency fingerprints. A source quote proves binding, not truth/semantic entailment. Risk class is never inferred and manual classification confidence accepts only categorical review states. Legacy JSON remains unchanged/unverified unless explicitly imported; imports preserve unknowns and extra fields. Existing archived evidence and all previous revisions remain retained.

Limitations: automatic product scoping requires explicit labels in the same passage; ambiguous/unlabelled sources abstain. Literal differences may over-report conflicts; semantic accuracy is unmeasured. One current product profile per project; legacy assessment integration uses local project. Source selection is bounded and visibly partial when capped; OCR-derived spans are excluded. Editors are self-declared rather than authenticated. Re-extraction refuses to erase reviewed decisions; explicitly reject reviewed fields before replacement. History lookup is linear; failed publication may leave unreachable revisions. Earlier Stage 02 OCR quality and index/manifest transaction limitations are unchanged.

Cost/latency: 0 live model/cloud/API calls; $0 cloud spend; no downloads, legal fetch, dependency installation or user-corpus/index rebuild. Temporary real Chroma is exercised only by existing offline synthetic tests. Deterministic preview uses local hash/JSON IO; optional model preview permits one generation plus one schema-repair under shared budget/transport deadlines and existing bounded transient retries. Repeated --llm previews can consume inference again; no global cache or performance benchmark claimed. Profile revisions/source views are private ignored state.

Rollback: revert only this Stage 03 commit to the prior baseline f4d9206; preserve state/ingestion, state/profiles, assessment snapshots and all originals. Older code does not consume new profile revisions, so retain this reader/export JSON before rollback. No data rollback or cleanup was performed. No push or deployment is authorized/performed.

Commit: User explicitly requested a new commit on the same branch, overriding the prompt pack's default no-commit instruction. Commit subject: Implement Stage 03 evidence-linked device profiles and audited review. See git log for the resulting commit ID.
Next stage: `docs/day_two_prompts/stages/04_REGULATORY_REGISTRY.md`. STOP after Stage 03 and the user-requested commit on the existing branch.


## Stage 04 implementation in progress (2026-10-17)

STAGE_04=IN_PROGRESS. Baseline a3d73ae on feat/stage-01-foundations-telemetry; initially clean tree. Read full Stage 04, AGENTS, architecture/test matrix, README, Stage 01 contracts/ledger, Stage 02 archive, Stage 03 decisions, draft extraction and review/report paths. Plan: separate project-scoped SQLite edition/provision/coverage tables and transactional audited lifecycle; exact archived-source import/export with draft-only imports; active-law and coverage/currentness gates; additive CLI and guarded review/report integration; negative/offline/fault tests, full regression, docs and same-branch user-authorized commit. No legal fetch, model downloads, new dependencies or next-stage work.

## Final Stage 04 gate (2026-10-17)

STAGE_04=PASS. Stage 05 has not started. This is an implementation/test gate, not verification of any real legal edition or device conformity.

Actual files:
- regulatory_registry.py: typed edition/provision/coverage/bundle/export/attestation contracts; separate project-scoped SQLite migrations/tables; immutable payload hashes; exact source binding; transactional revision/audit/idempotency; human lifecycle; dated active-law, amendment, dependency, rights and coverage gates.
- registry_cli.py and main.py: registry-import/export/review/coverage/check/schema and additive review --registry-edition/--registry-as-of flags. Imported exported approval flags never grant authority; explicit legacy draft conversion remains proposed.
- registry_adapter.py, review_state.py and report_state.py: approved-only register adapter, frozen registry selection/revision in assessment scope, resume/render integration and export revalidation. Inactive/retired/changed requirements block current registry-backed reports before file publication.
- Q_Mix_report_writer.py: visible registry authority, coverage and warning lines; legacy reports remain research-only, never authoritative law.
- telemetry.py: allowlist legal_registry_not_ready without raw exception logging.
- tests/test_regulatory_registry.py: 69 synthetic offline cases. Existing test files unchanged.
- registry.example.json: empty schema-valid bundle, no normative seed. README plus decisions/progress explain usage, compatibility and limits. No requirements/.env/rag.py or client source/index files modified.

Measured validation:

| Check | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q tests/test_regulatory_registry.py -p no:cacheprovider` | PASS: 69 passed in 10.37s |
| Earlier existing report-state/orchestrator/day-two-baseline/foundations suite | PASS: 139 passed in 41.58s |
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | PASS: 574 passed, 1 skipped in 128.30s (2m08s); no warnings |
| `.\.venv\Scripts\python.exe -m compileall -q main.py mdr_rag tests/test_regulatory_registry.py` | PASS |
| Main/registry-import/review help, AST parsing, empty template validation, ignored registry storage | PASS: all 19 existing commands retained; six registry commands added |
| git diff --check and new-file whitespace | PASS |
| Ruff/Black/mypy | NOT RUN: not installed/configured; no tool installation |
| Real Ollama, OCR, cross-encoder, browser UI, actual legal-source/expert verification | NOT RUN: no live integrations or real law attestation claimed; existing optional real-model test skipped |

Negative/fault checks cover missing law/URL/dates, lifecycle skipping, imported active flags, inactive/draft/withdrawn requirements, forged quotes/pages/hashes, same-section IDs across editions, duplicate clauses, conflicting amendments and sections, cyclic lineage, future/stale effective and approval dates, verified superseding amendment blocks, coverage missing a selected section, dependencies invalidated by retirement, standards rights and nonbinding guidance, cross-project/device-source rejection, immutable edits, optimistic concurrency, consistent read snapshots, interrupted transactional publication, newer schema rejection, export content roundtrip/tampering, schema error redaction, and inert uploaded instructions. Test-only fixture selectors exercise report integration while production selection refuses synthetic authority.

Compatibility/deviations: legacy draft extraction and ordinary review retain their existing evidence-research workflow but now explicitly report draft_research_only, partial registry coverage and legal_registry_not_ready. Authoritative registry-backed review/check fails before inference without approved active law. This preserves legacy commands/tests without promoting drafts. The actual applicability engine remains Stage 05; no current law or full legal coverage is invented. Existing assessments/SourceBuffer and runtime ledger retain their ownership.

Limits: one legal edition/local-project legacy review integration per assessment; cross-edition composition deferred. Real source authority, legal dates, rights, professional qualification and normative scope remain human responsibilities; reviewer labels are self-declared. Coverage completeness is only within the manually approved section inventory and does not prove exhaustive obligations. Standards/guidance never become binding law merely by mention. Registry-backed review still requires the existing matching live corpus/index; no index rebuild occurs automatically. Retired snapshots remain historical rather than current selectable law. Original archives are required, repeated hash checks can be IO-heavy, and no dossier performance benchmark is claimed. SQLite selection is coherent, but later filesystem report publication is not one atomic cross-store transaction; reports are dated revision snapshots. No automatic approval renewal/deletion/network synchronization.

Cost: 0 live model/API/network calls, $0 cloud spend, no downloads, dependency installation, legal fetch or user corpus/index rebuild. Registry administration is deterministic local SQLite/JSON/hash IO. Existing temporary Chroma tests use fake embeddings; model operations continue using Stage 01 guards if the existing optional drafting workflow is invoked. Test artifacts/runtime state remain ignored.

Rollback: revert only the Stage 04 commit back to a3d73ae while retaining state/regulatory_registry, state/ingestion, state/profiles and all assessment/source histories. Earlier code ignores the new registry database and cannot validate new registry-bound reports; retain this reader or export labelled historical snapshots. No data cleanup or rollback was performed.

Commit: explicitly authorized by the user on the existing feat/stage-01-foundations-telemetry branch. Subject: Implement Stage 04 reviewed regulatory registry and active-law report gates. No push/deployment.
Next stage: `docs/day_two_prompts/stages/05_APPLICABILITY_ENGINE.md`. STOP after the Stage 04 commit.


## Stage 05 implementation in progress (2026-10-17)

STAGE_05=IN_PROGRESS. Baseline 195294d on feat/stage-01-foundations-telemetry; initially clean tree. Inspected full Stage 05/AGENTS/architecture/test matrix, Stage 03 profile provenance and audit, Stage 04 active registry gates, legacy applicability roles and durable review/report dependencies. Plan: bounded typed tri-state rules and exact legal condition references; immutable specialist rule approvals/retirement and source-backed overrides; relevant-field evaluation cache, unknown/conflict/high-impact/classification review handling; optional bounded advisory interpretation that cannot change decisions; additive CLI and nested review compatibility; focused fault/metamorphic tests, full regression, docs and user-requested same-branch commit. No synthetic law/rule seed, legal fetch, downloads, dependency changes or Stage 06.

## Final Stage 05 gate (2026-10-17)

STAGE_05=PASS. Stage 06 has not started. This is a software/offline test gate, not verification of real legal rules, a device classification or conformity.

Actual changes:
- applicability_rules.py: bounded typed JSON predicates, true/false/unknown composition, exception precedence, exact legal condition references, five-state candidate assessment, source-backed exclusion rationale, high-impact/conflict/composite review queues, and candidate-only classification with a known device-source prerequisite.
- applicability_service.py: immutable project-scoped rulebook revisions, explicit specialist approvals/retirement, dated rule selection, audit/idempotency/optimistic revision guards, relevant-input evaluation cache and source-bound overrides. Source/registry/rule validity are checked before cache reuse; old sources and decisions remain immutable. Publication rejects oversized revisions before advancing the head.
- applicability_cli.py and main.py: seven additive schema/show/import/approve/retire/evaluate/override commands; explicit dated local advisory opt-in. No rules/law/classification seed.
- applicability.py, roles.py, registry_adapter.py and review_state.py: nested typed candidate result for explicit registry-backed contexts; preserved outer legacy status vocabulary, rule/override/engine dependency bindings and current-report invalidation. Injected legacy draft metadata alone cannot enable the registry engine.
- Q_Mix_report_writer.py: separate candidate applicability and evidence-status presentation with review-required category labels.
- tests/test_applicability_engine.py: 92 new synthetic tests reusing the existing clearly labelled toy registry fixture. All pre-existing test files unchanged. README/decisions/progress updated; requirements/.env/rag.py, user originals and user indexes unchanged.

Measured checks:

| Command/check | Exact result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q tests/test_applicability_engine.py -p no:cacheprovider` | PASS: 92 passed in 35.72s on final production code |
| Existing registry/orchestrator/report plus initial applicability cases | PASS: 196 passed in 117.19s; intermediate compatibility run |
| Earlier full suite before the final classification-source guard | PASS: 665 passed, 1 skipped in 244.96s; intermediate only, superseded |
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | PASS: 666 passed, 1 skipped in 171.21s; no warnings |
| Stronger non-null classification/name-edit metamorphic case, same production code | PASS: 1 passed in 13.05s; test-only assertion strengthening during the final full run was verified separately |
| `.\.venv\Scripts\python.exe -m compileall -q main.py mdr_rag tests/test_applicability_engine.py` | PASS after final source changes |
| Main/applicability-override CLI help; AST; tracked/new-file whitespace and ignore checks | PASS; all 25 existing commands retained and seven new commands added |
| Ruff/Black/mypy | NOT RUN: not installed/configured; no tool installation |
| Real Ollama/OCR/cross-encoder/browser/actual specialist legal interpretation and calibration | NOT RUN; existing opt-in real-model smoke skipped, not counted as a passed integration |

Tests cover all three-state Boolean tables, supported positive/negative routing and missing-vs-false fields, unknown exceptions, explicit exception precedence, exclusion rationale/source requirements, high-impact sterility/invasiveness, conflicting population, composite purpose, modal/normative wording, unknown/unsourced/manual/pending attributes, candidate-only classification and no label from unconditional law without device facts. They also cover rule approval/expiry/conflicts/retirement, edition isolation and forged/unrelated legal references, active-law blocking before model/cache access, current report binding invalidation, repeated evaluation and irrelevant-name cache reuse versus relevant-field invalidation, source/cache/revision tampering, stale/idempotent writes, interrupted head publication, source-preserving audited overrides, injected DSL/review metadata, bounded trees, missing schema/source advice, cancellation, offline/timeout/model/budget fallback and actual guarded-provider fakes with redacted failure logs.

A final code review found that an unconditional reviewed law-only predicate could attach a category label with no known device attribute. The implementation now withholds that label, returns requires_human_review and asks for sourced device qualification predicates. The 92-case focused and final 666-case complete runs include the regression. The later test-only metamorphic strengthening explicitly checks a non-null classification candidate rather than a trivial absent label; it passed separately without production-code changes.

Compatibility: ordinary draft research retains its previous uncertain actor assessment and never gains registry authority from metadata. Registry-backed runs preserve old outer applicable/uncertain/possibly_not_applicable values and store the complete five-state result under candidate_assessment. Not-applicable routing does not become evidence sufficiency or suppress evidence review. Old snapshots remain readable with this code; Stage 04 snapshots require explicit current revalidation for new rule bindings, or historical rendering. No automatic assessment/index/source migration.

Limits/tradeoffs: verified rule semantics and source-fact truth still require humans; quote binding is not entailment. Reviewer identity/qualification is self-declared. Literal/Boolean normalization does not infer synonyms, units, clinical interpretation or definitive class. High-impact routing needs explicit specialist review; classification always remains candidate/requires_review. Unknown/conflicting facts cannot be overridden into unsupported exclusion; correct the sourced profile or reviewed rule first. Manual facts lacking document support remain unresolved for automatic predicates. One applicable approved rule per provision/date, active same-edition references and local-project legacy review integration; cross-edition composition and classification certification are out of scope.

The relevant-field cache excludes cosmetic name/profile revision changes but includes engine/date/edition/provision/rule/source/review/conflict inputs. Actual profile/registry revisions are returned separately. Existing whole-assessment profile invalidation remains broader. Private 20 MiB-bounded snapshots/cache, linear audit lookup and repeated original hashing add local IO; failures can leave unreachable immutable revisions while preserving the old head. No automatic GC/renewal or cross-store atomic publication/currentness guarantee. Every output is a dated source/revision snapshot.

Cost/latency: 0 live model/cloud/API calls and $0 cloud spend; no legal fetch, downloads, dependency installation or user-corpus/index rebuild. Deterministic applicability uses zero model calls. Optional advisory requests share existing durable invocation budgets/deadlines/transient retries, cannot change predicate decisions and preserve uncertainty on failure. Repeated ambiguous --assist calls can consume new inference; no cross-run advisory cache or model/accuracy/dossier latency benchmark claimed. Full-suite timing above is test runtime only.

Rollback: revert only the Stage 05 commit to 195294d; preserve state/applicability, state/regulatory_registry, state/profiles, source archives and assessment histories. Earlier readers may reject the new nested applicability fields/method, so keep this reader or export reports first. No source/cache/history deletion or data rollback was performed.

Commit: explicitly authorized by the user on feat/stage-01-foundations-telemetry. Subject: Implement Stage 05 sourced applicability rules and specialist review. No push/deployment.
Next stage: `docs/day_two_prompts/stages/06_RETRIEVAL_AND_RERANKING.md`. STOP after this stage and the requested same-branch commit.


## Stage 06 execution plan (2026-10-17)

Status: IN_PROGRESS. Baseline: 7699e40, clean feat/stage-01-foundations-telemetry. Read full Stage 06/reference specs, day_two_prompts/AGENTS.md (no root AGENTS.md), README, main/Streamlit, ingestion/parser, search/query planner/reranking/evidence gate and relevant tests/config. Existing hybrid/RRF, 4-query planner, optional pinned CPU scorer, calibrated evidence gate and immutable ingestion are retained. eval/gold_queries.json is empty; examples explicitly are not human calibration.

Plan: (1) freeze a clearly synthetic regression fixture and measure existing BM25 baseline before changes; (2) add optional structural child indexes with canonical parent citations and project/document/model revision identity, bounded cached expansion and explicit retrieval fallback diagnostics; (3) exercise stale/deleted/duplicate sources, no evidence, failure paths and 1000+ chunks offline; (4) record comparative fixture metrics, run focused/full checks, inspect diff and commit on the current branch. Existing retrieval defaults stay unchanged without held-out expert evidence. No network/models/dependency installs or user index rebuild. Expert benchmark/calibration remains NOT RUN pending authentic labels, never replaced by synthetic claims.

## Final Stage 06 gate (2026-10-17)

**STAGE_06=PASS — implementation/offline gate.** Expert relevance calibration,
real-model comparative quality and default promotion remain NOT RUN / not approved.
Existing hybrid defaults remain unchanged. Stage 07 is not started.

Implemented: optional content-addressed project/corpus/document/extraction/model/revision
structural child indexes; exact canonical parent return/SourceBuffer recording; dedicated optional
Chroma collections; BM25Plus(delta=0) only for the opt-in resilient path; bounded cached search aliases
with one optional structured local selection; lexical and fusion fallback codes; model-revision
bindings in existing indexes, saved config, assessment dependencies and evidence calibration;
query/candidate/character caps, source/version inventory checks and redacted retrieval telemetry.
No definitive classification/conformity or relevance confidence is produced.

Changed files:
- main.py and new mdr_rag/retrieval_cli.py: two explicit commands; all existing commands retained.
- New mdr_rag/structural_retrieval.py, retrieval_safety.py, query_expansion.py and retrieval_benchmark.py.
- mdr_rag/search.py, pipeline.py, query_planner.py, reranking.py: scoped extensions preserving legacy defaults.
- mdr_rag/settings.py, saved_configuration.py, review_state.py, evidence_gate.py, telemetry.py and .env.example: revision/config/logging contracts.
- New tests/test_stage06_retrieval.py (51 deterministic tests), two eval/stage06_synthetic_*.json artifacts,
  README and implementation progress/decisions/RETRIEVAL_STAGE06.md.

Measured checks:
| Command/check | Result |
|---|---|
| Pre-change retrieval/reranker focused suite | PASS: 59 passed, 1 optional model skipped, 8.58s |
| Intermediate retrieval/reranker/ingestion compatibility suite | PASS: 124 passed, 1 skipped, 13.57s |
| Initial new Stage 06 suite | PASS: 39 passed, 3.81s |
| Expanded new Stage 06 suite | PASS: 50 passed, 3.14s |
| Intermediate full suite before standalone scope fix | PASS: 716 passed, 1 skipped, 149.58s; superseded |
| Final focused: python -m pytest -q tests/test_stage06_retrieval.py tests/test_query_retrieval.py -p no:cacheprovider | PASS: 78 passed (51 new + 27 existing), 8.25s |
| Final full: python -m pytest -q -p no:cacheprovider | PASS: 717 passed, 1 optional real-model skipped, 144.44s |
| python -m compileall -q main.py mdr_rag tests/test_stage06_retrieval.py | PASS on final production source |
| AST parse of main/module files and new test | PASS: 55 files |
| python main.py retrieval-index --help; python main.py retrieve --help | PASS, no models |
| python -m mdr_rag.retrieval_benchmark --out reports/stage06/comparison-final.json | PASS; all seven fixed synthetic cases, matching baseline fixture hash |
| git diff --check; reviewed changed/new files and fixture/key markers | PASS |
| Ruff/Black/mypy | NOT RUN: none installed/configured; no tool/dependency installation |
| Real dense/LLM/cross-encoder quality/inference, OCR/browser, expert held-out labels/calibration | NOT RUN; synthetic vectors test local Chroma mechanics only |

All Python checks used .venv/Scripts/python.exe. Tests cover exact clauses, abbreviations,
multilingual text, negation, table boundaries, long atomic text, literal no-match abstention,
keyword stuffing, 1,016 chunks, duplicate/current/versioned sources, cross-project/corpus isolation,
archive/index tampering, missing dense resources, deterministic local Chroma, unavailable/timed-out
models/rerankers, schema failures, cancellation, shared budget exhaustion, failed publication,
Windows labels, CLI flow, revision-bound cache/config/calibration and fixed-code private logs.

Final review found a standalone programmatic budget boundary: CLI calls already shared a run, but
multiple batches through the new API needed a lazy outer scope. Added scopes to structural build/
retrieve and shared candidate retrieval plus a regression proving only one operation executes
under a one-call budget across multiple batches, with no partial index publication. The final
focused and 717-test full suite include this fix. No existing test was weakened/deleted.

Synthetic measurements: baseline 8.39 ms mean; final legacy BM25 11.25 ms; structural 27.77 ms;
expanded structural 22.26 ms. All three final paths and baseline Recall@5/10, MRR and nDCG are 1.00
on six literal answerable illustrations; the seventh unmatched case is retained, zero-match 1/7.
Final p95 values: 22.66 / 62.38 / 23.11 ms. In-memory scoring only, small/noisy and concurrent with
the suite; no performance/quality gains claimed. Artifacts and per-slice results are tracked.
No authentic expert gold was available; no threshold was fabricated or promoted.

Compatibility/risks: existing source spans, legal authority and assessment output contracts remain
canonical; the new commands return candidates requiring verification, not accepted evidence.
Existing empty revision configs remain loadable. Explicit EMBEDDING_REVISION binds new vectors/
config/calibration; mutable model-tag changes remain operator-managed. Literal boundaries cannot
repair pre-existing extraction cuts/PDF table ambiguity. Atomic oversized paragraphs remain whole.
CLI checks selected working files; historical API use is explicit and newly added documents need
a new snapshot. No cross-store transaction or concurrent builder guarantee; failed late publication
may retain unreachable immutable artifacts. Snapshot verification adds IO. Native CPU calls use
cooperative deadlines/late-result rejection, not a hard-kill process boundary. See detailed report.

Costs: 0 live model/cloud calls, $0 cloud spend, no model/download/network/legal fetch, dependency
changes, user dossier/index rebuild, push or deployment. Optional inference shares existing durable
budgets/timeouts/retries and never downloads weights implicitly. Model quality/latency NOT RUN.

Rollback: revert only this Stage 06 commit to 7699e40 and preserve all source/assessment/profile/
registry/applicability/retrieval archives. Restore prior explicit embedding settings for prior vectors;
keep this reader or export new-configuration reports first. No data deletion was performed.

Commit explicitly authorized by the user on feat/stage-01-foundations-telemetry.
Next: docs/day_two_prompts/stages/07_EVIDENCE_AND_CITATION_AUDIT.md. STOP after requested commit.
