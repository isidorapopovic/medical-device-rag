# Stage 7 verification

Verified on 2026-10-13 on `qmatrix-impelmantion`, based on Stage 6 commit `b1d0d3dbb0230ca42d519137558d35550de931df`. Implementation commit: see Git history for "Stage 7: Wire typed assessment roles and saved-state CLI orchestration".

## Implemented behavior

- `AssessmentOrchestrator` connects Requirement Analyst, Applicability Analyst, Evidence Retriever, Evidence Reviewer, Citation Auditor and Report Writer. Typed outputs are `VersionedRegister`, `ApplicabilityResult`, `RetrievalResult`, `ReviewedFinding`, `AuditResult` and `ReportExport`. Retriever/reviewer dispatch rejects work outside their stage boundaries. Existing query planning, retrieval/fusion, reranking, gate, immutable source snapshots and claim-review/repair helpers are reused. `pipeline.py` remains the compatibility facade; extraction implementation now belongs to the Requirement Analyst.
- Extraction preserves stable IDs and requirement revisions, validates register fingerprints and archives previous/new registers. It uses the existing exclusive lock and atomic writer with an optimistic content check before publishing. Resume never calls extraction. The register's historical bytes and SourceBuffer snapshots remain available.
- Initial applicability assessment is deterministic and conservative: an actor condition is used only when literally found in a verified legal anchor; profile facts are explicitly unverified. A conflicting unverified `actor_role` can yield tentative `possibly_not_applicable`; missing or unsourced conditions remain uncertain. Missing facts and legal citations are persisted. Both results use `search_device_evidence`; tentative scope never skips retrieval. Applicability and evidence status are rendered separately.
- Continuation and current report rendering resolve settings from saved state, including pinned calibration contents. Explicit CLI overrides invalidate affected dependencies. `--use-env-config` explicitly adopts current environment settings. Manifest validation and inference execute under resolved settings in a scoped environment, restored on exit/interruption. Current implementation/scorer/source/profile dependencies still validate before reuse.
- `--reranker` aliases `--rerank-backend`, preserving `--rerank`. Existing assessment IDs, resume, targeted refresh and rendering remain available. Positive limits/k, known IDs and incompatible options are validated. Refresh creates a section revision; resume continues unfinished/stale work. Counts derive from the full assessment.
- JSON/Markdown preserve compatibility fields and show applicability/missing facts, claim inventories and quoted source spans, gate calibration, review/audit outcomes and execution state. The writer adds no findings. Graphs retain legacy citation metrics and distinguish retrieved, raw-cited, contradiction, legal-scope and reported model-audited support edges. Pending/failed/stale requirements are included without being counted as missing documentation. Legacy audit limitations remain explicit and cannot acquire audited-support edges merely through import.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage7-before -p no:cacheprovider --tb=short
# Baseline: 257 passed, 1 skipped in 197.72 seconds; no pre-existing failures.
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage7-full -p no:cacheprovider --tb=short
# Full suite: 274 passed, 1 skipped in 201.99 seconds.
.\.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py tests/test_evaluation.py -q --basetemp reports/test-temp-stage7-display-final -p no:cacheprovider --tb=short
# Final display checks: 26 passed in 20.99 seconds.
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe main.py review --help
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Help, dependency consistency and whitespace checks passed. Seventeen new synthetic cases cover complete extraction-to-report six-role execution with the `--reranker` alias, gate short-circuit, invalid schema/failed graphs, interrupted CLI resume, targeted refresh preserving unaffected sections, reviewer repair budget, saved-versus-explicit settings, legacy graph/export compatibility, unknown scope conditions, cross-role rejection and truthful full-state partial counts. The final display checks use the exact `--retrieval hybrid --reranker cross_encoder` command shape and explicitly check experimental gate labels versus strict validation counts.

Existing fixtures now opt into `--use-env-config`/`use_env_config=True` where intentionally adopting changed model/calibration settings; silent ambient environment changes are no longer a resume override. The simulated schema-1 fixture omits the new applicability field, preserving its original audit limitations. Intermediate extraction failures identified missing helper binding and a lock-call signature error; these were corrected and covered by the existing extraction tests and new end-to-end workflow.

All new model/scoring responses use deterministic synthetic fixtures. The end-to-end test forbids live Ollama calls, uses fake cross-encoder scoring and mocked embeddings, and performs no model download or index rebuild. No real semantic/retrieval performance or threshold was measured. The opt-in real-model test remains skipped. The user's `.env`, documents, register, existing index and existing reports were preserved; synthetic outputs reside beneath ignored `reports/test-temp-stage7-*` directories. Streamlit controls were not added.
