# Day Two Stage 00 baseline and risks

Audit date: 2026-10-16. Stage 00 only; no architecture migration, model download, index rebuild, cloud request or assessment run. See CURRENT_ARCHITECTURE.md for flow, flags and symbol inventory.

## Environment and command record

Windows PowerShell; system and existing virtual environment both use Python 3.13.3, rather than the pack's recommended 3.11/3.12. Use `.\.venv\Scripts\python.exe` explicitly.

| Command / check | Result |
|---|---|
| `python --version` | PASS: Python 3.13.3 |
| `python main.py --help` | FAIL: system Python lacks dotenv |
| `python -m pytest -q` | FAIL: system Python lacks pytest |
| `.\.venv\Scripts\python.exe --version` | PASS: Python 3.13.3 |
| `.\.venv\Scripts\python.exe main.py --help` | PASS: all 13 commands exposed |
| `.\.venv\Scripts\python.exe -m pytest -q tests/test_daytwo_baseline.py --basetemp reports/test-temp-daytwo-focused` | PASS: 17 tests, 8.27 seconds |
| Full existing offline suite | Result appended below after completion |
| Safe inspect smoke | Empty temporary corpus inspected; synthetic text sample rerun after fixing shell stdin Unicode encoding. Initial literal Unicode stdin attempt failed with Windows invalid filename because the shell replaced a character with `?`; escaped Unicode avoids that transport issue. |
| `git check-ignore` for .env, legal/device samples, state, reports, vector_db | PASS: all ignored |
| `git ls-files documents state reports vector_db .env` | Only legal/device .gitkeep placeholders tracked in these paths |
| Lint/format | NOT RUN: no configured tool found |
| Live Ollama / actual model inference / real cross-encoder | NOT RUN: outside offline baseline; no downloads or service changes |
| Streamlit browser / full assessment / real benchmark | NOT RUN: later-stage work, requires reviewed data and runtime |

Installed versions from virtual environment package metadata: ollama 0.6.3; chromadb 1.5.9; PyMuPDF 1.28.2; python-docx 1.2.0; python-dotenv 1.2.4; pydantic 2.14.0; rank-bm25 0.2.2; pytest 9.1.1; numpy 2.5.4; scikit-learn 1.9.1; plotly 6.9.0; pandas 3.0.6; networkx 3.7; streamlit 1.65.0. These are observed installed metadata, not a newly tested lockfile or recommendation.

## Characterization and smoke matrix

New tests cover six legacy dispatch paths, four invalid argument forms, empty corpus, spaces/Unicode filenames, same-name files in different corpora, no overwrite, exact citation locations, empty index safety, retrieval config validation before DB access, missing manifest CLI error, malformed JSON, and simulated offline embedding failure with exactly one call. Existing suites additionally cover report state, raw spans, query fusion, gate/calibration, claim auditing, production evaluation, upload handling, saved configuration and report exports. All new text is clearly invented test content.

Missing `.env`: full isolated startup without that file has NOT RUN; python-dotenv loading is optional in code, but package installation remains mandatory. Legacy execution avoidance was inspected statically (main/Streamlit do not import rag.py); no legacy import was attempted. The offline provider failure test records propagation of ConnectionError, not a graceful CLI recovery promise.

## Actual risks and gaps

1. Index rebuild deletes the existing modular collection before embedding completes: offline Ollama can leave a partial/empty replacement. Preserve current index; future migration needs staged rebuild/atomic activation.
2. CLI exception handling covers selected ValueError/RuntimeError/file errors; provider ConnectionError may escape with a traceback. Characterized, not silently changed.
3. Draft extracted requirements and an edition label are not a curated, verified legal registry. Coverage and legal currentness remain unverified. No authoritative law was fetched or generated here.
4. JSON state already has locks and immutable revisions. SQLite is a future compatibility migration, not a missing import to add now. Document versions/project isolation and a reviewer-approved registry require explicit contracts.
5. UI currently manages files only. No profile review, requirement selection, human adjudication workflow or full assessment dashboard. Preview catches broad Exception and shows raw errors; operational logging/privacy controls need review.
6. UI has no authentication; keep its listener at localhost using `--server.address 127.0.0.1`. Upload extension and size controls are not MIME validation, malware scanning, decompression limits or OCR. DOCX order and PDF reading order need further provenance/quality tests.
7. Call/token/spend/time budgets from this pack are not run-wide enforced controls yet. Optional cloud/OCR settings must not be assumed implemented. Ollama host configuration, telemetry behavior of dependencies and network isolation have not been dynamically audited; local-model architecture alone does not prove zero network traffic.
8. `eval/gold_queries.json` is an empty set. Example/toy labels are not real benchmarks; no accuracy, recall or latency claims can be made for project data. Strict gate needs independent calibration labels.
9. Requirements use version ranges; Python 3.13 works for observed tests only. Optional heavy pinned dependencies/model integration were not installed or validated here.
10. README links to old `docs/stage*_verification.md` locations are broken in the incoming working tree, which already moves documents into day_one_prompts. Preserve user moves; repair links separately if desired.

## Privacy and preservation

Eight PDF files exist in source directories; their contents/names were not copied into this audit or used for model inference. Existing .env values were not read or printed. Source corpora, profile, vector store, state and reports are ignored, and no such private files were found tracked by the scoped git audit. This is not a full secret scan of repository history. JSON/Markdown/HTML reports and evidence traces contain source text and must remain private. Ignore rules do not protect files already tracked elsewhere or exports outside ignored folders.

Existing user changes include deleted old documentation, new day_one_prompts/day_two_prompts folders and an untracked `how HEAD` file. They were left intact. No commit was created because those unrelated changes should not be staged as part of this baseline.

## Preservation plan, cost and rollback

Preserve main.py, streamlit_app.py, rag.py, all mdr_rag modules and existing tests. Stage 01 should build adapters around existing schemas/state rather than replace the workflow. Keep existing environment names and all CLI flags; introduce versioned migrations only after compatibility tests pass. No feature flags/defaults changed.

Model calls: 0 real calls; fake embedding failure only. Cloud spend: $0. Timings here are test runtime, not model performance. No dependency installation or source/index/state migration performed.

Rollback only this increment by removing `tests/test_daytwo_baseline.py`, `docs/CURRENT_ARCHITECTURE.md` and this file (plus the generated symbol inventory embedded in CURRENT_ARCHITECTURE). Preserve all pre-existing changes. Test temp folders are under ignored reports; they contain test fixtures only.

Next stage: `docs/day_two_prompts/stages/01_FOUNDATIONS_AND_CONTRACTS.md`, only after a new user instruction. Stage 00 does not establish production or regulatory readiness.

Additional observed Windows edge case: the escaped Unicode sample was created correctly but inspect raised UnicodeEncodeError with default CP1252 stdout. Repeating the synthetic smoke with sys.stdout.reconfigure(encoding='utf-8') passed and printed the text-file location. Use Python -X utf8 for Unicode console output. No application fix was introduced in this audit.

Additional contract mismatch: current ApplicabilityResult uses applicable/uncertain/possibly_not_applicable, while the new pack proposes applicable/not_applicable/conditional/unknown/requires_human_review. Existing analyst deliberately never confirms unverified profile facts. Stage 01 must preserve serialized compatibility or supply an explicit migration.

Static checks: Python compileall for main.py, streamlit_app.py, mdr_rag and the new test file PASS; git diff --check PASS (tracked changes only). Git emits a permission warning for the global ignore file, but repository ignore checks succeed.

Final existing-suite result: .\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-daytwo-stage00 — PASS: 301 passed, 1 skipped in 325.94 seconds (5m25s). The skipped test is the explicit opt-in real CPU cross-encoder smoke (RUN_CROSS_ENCODER_SMOKE not enabled); it is NOT RUN, not a model integration pass. This suite was collected before the new file was added; the 17 new tests passed separately. Total observed: 318 passed, 1 skipped across the two invocations.

Stage 00 gate: deterministic baseline passes using the existing virtual environment. System interpreter dependency failures and the CP1252 Unicode console failure remain documented. Stop here; Stage 01 has not started.
