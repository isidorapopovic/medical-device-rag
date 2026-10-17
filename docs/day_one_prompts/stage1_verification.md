# Stage 1 verification

Verified on 2026-10-13 in the working tree on `qmatrix-impelmantion`, based on Stage 0 commit `a44810ad842f5c553cc270cf7f3fc6b0bc58bf66`. Implementation commit: see Git history for "Add resumable assessment state and targeted review updates" on `qmatrix-impelmantion`.

## Implemented behavior

- `report_state.py` defines typed schema-v1 `ReportState`, `RequirementSection`, register records, passages, dependencies and stage events. Findings retain their existing typed schema. Unknown versions, invalid identities, malformed checkpoints/history and inconsistent requirement hashes are rejected without overwriting canonical state.
- Canonical files live at `state/assessments/<assessment_id>/report_state.json`; numbered committed snapshots live in `revisions/`. Same-directory temporary files are flushed/fsynced and replaced atomically. A crash between canonical commit and latest-history export can leave one missing history file; the next mutation archives that committed canonical revision before advancing.
- An exclusive file lock covers a whole assessment mutation/review; save also checks expected revision. Conflicts explain how to wait/reload or investigate a crashed writer. Locks are never silently broken.
- The existing pipeline checkpoints unverified applicability context, single-query construction, retrieval, structured generation and citation-ID publication. Resume reuses only completed valid checkpoints and never runs extraction. A failed operation records its stage and exception type without storing a potentially confidential exception message. Abrupt interruption leaves the previous durable checkpoint available.
- Targeted updates preserve unchanged sections, including finding content, timestamps, finding revision numbers and human annotations. Published finding history retains the requirement/evidence/dependency snapshot for each revision. Aggregate counts derive from the full saved assessment.
- Profile, requirement, query, corpus, retrieval/backend/calibration identity, generation/prompt/schema and validation fingerprints determine the earliest invalidated stage. Uncited new files invalidate every retrieval-dependent section. Unindexed source changes mark saved findings stale without rebuilding the index. Removed IDs/new legal documents require a new assessment instead of dropping existing sections.
- Per-assessment `assessment.json`/`assessment.md` exports preserve compatibility fields. Successful reviews also refresh traditional latest exports in `reports/`. Stale findings are excluded from current counts; explicit historical exports show previous findings and are clearly labelled. Historical rendering can select a saved state revision without reading live source files or calling inference.
- Explicit `import-legacy` writes a new assessment only, preserves original source bytes and report provenance, retains original IDs/statuses/timestamps/limitations, and marks imported findings `legacy_unverified`, `human_validated=false`. Missing requirements in partial reports are counted without inventing them. Current reuse requires dependency validation and recomputation.
- New extraction IDs depend on legal anchors/provision/normalized quote position rather than model-written paraphrases. Matching existing anchors retain original IDs; changed wording increments requirement revision and records prior content.

## Checks and results

Using the existing project virtual environment (the system Python still lacks project dependencies):

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage1-before
# 31 passed before implementation
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage1-final
# 70 passed after implementation
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe main.py review --help
.\.venv\Scripts\python.exe main.py report --help
.\.venv\Scripts\python.exe main.py import-legacy --help
git diff --check
```

All checks passed. The 39 new synthetic tests cover interruption after retrieval/drafting, safe failure resume, targeted refresh/edit isolation, dependency invalidation, new uncited sources, current/historical rendering, revision conflicts, lock contention in a separate Python process, malformed states, atomic-replacement interruptions before/after canonical commit, legacy import/recompute, deterministic requirement identity and CLI validation. No new regressions or assertion failures; dedicated test temp paths avoid the Stage 0 Windows temp-directory permission problem.

## Preservation and limitations

No live corpus review, extraction, migration or index operation was executed. The user's `.env`, documents, profile, original requirement register, manifest, vector database and generated assessments were not changed. All persistence/migration tests use isolated synthetic fixtures beneath dedicated test directories in ignored `reports/`; CLI help calls do not perform inference. Verification involved no model downloads, network inference or later-stage implementation. The Stage 1 source changes and this verification note are committed separately from all local test outputs.

This stage makes the existing pipeline durable; it does not validate its legal reasoning. Applicability remains explicitly uncertain. The only new-publication audit is citation-ID membership, with `audit_status=identifier_checked_only`. Independent semantic review, SourceBuffer/raw-span auditing, multi-query planning, cross-encoder reranking and calibrated evidence gates remain pending. Calibration identity is currently an explicit `not_implemented` fingerprint placeholder, not a claimed calibration artifact. Model fingerprints cover configured tags/settings, not weight digests: changing weights under the same tag requires explicit refresh. Normalized quotation positions are register identities, not raw-span evidence. JSON/Markdown exports are independently atomic and serialized, but not a two-file transaction; regenerate them from canonical state after an export interruption.
