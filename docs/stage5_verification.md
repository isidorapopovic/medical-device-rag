# Stage 5 verification

Verified on 2026-10-13 on `qmatrix-impelmantion`, based on Stage 4 commit `ba596338da99eda67337d04394b99cd5f578d3eb`. Implementation commit: see Git history for "Stage 5: Add calibrated evidence gating and held-out threshold evaluation".

## Implemented behavior

- Review checkpoints now include a persisted passage evidence gate between retrieval/reranking and drafting. Decisions retain scores, accepted/rejected IDs, reasons, drafting IDs and calibration/context fingerprints. Enabled gates screen the merged pool before selecting the drafting subset. Only that subset is presented to the drafting model. Empty or rejected pools produce `insufficient_evidence` without drafting, including an empty pool with the gate disabled.
- Strict mode is the default. Missing calibration abstains with `threshold_not_calibrated`; changed scorer, corpus, profile or retrieval configuration blocks calibration reuse. Experimental mode requires an explicit finite threshold. Disabled and experimental modes remain visible in compatibility exports and cannot count as successful strict validation.
- Only reranker scores are eligible. RRF and Chroma distances are not treated as relevance scores; no cosine metric is assumed or distance conversion introduced. Scoring failures, missing indexes and an unexpectedly empty indexed corpus are execution errors rather than missing-documentation findings.
- Calibration reads completed scored calls and immutable source snapshots from saved assessments. Human labels must cover every scored candidate, include positive passages and hard negatives, and include answerable and unanswerable cases in each split. Case IDs and original query fingerprints must be disjoint. Threshold selection uses the calibration split only; held-out metrics use the frozen threshold. Artifacts pin scorer revision/transformation, retrieval configuration, corpus/profile/label fingerprints, reviewer, metrics and creation date, and refuse overwriting an existing artifact.
- Current Ollama LLM reranker identity lacks an immutable weight digest, so it cannot produce a strict calibration artifact. Its experimental and disabled modes remain available. The pinned cross-encoder identity supports strict calibration; a threshold from another revision/backend cannot transfer silently.
- Coverage remains separate from passage relevance. Explicit atomic obligations and qualifiers are checked against accepted, raw-span-validated citations. Missing coverage requires review; incomplete qualifiers can demote a supported draft to partial. Coverage remains model self-assessment with raw citation checks, not a semantic proof of legal sufficiency.
- Resume retains completed gate decisions. Calibration changes invalidate the gate and downstream work; retrieval pool-policy changes invalidate retrieval. Targeted updates preserve unaffected sections. Existing snapshots and historical reports remain readable.
- A bounded Windows-only retry handles transient `PermissionError` during atomic replacement, using the same temporary file and destination under the existing lock/revision guard. Five attempts wait at most 0.5 seconds in total. Persistent denial still raises and preserves the prior file; no lock is overridden.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage5-before -p no:cacheprovider
# Baseline: 175 passed, 1 skipped; no pre-existing test failures.
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage5-confirmed -p no:cacheprovider
# Final: 215 passed, 1 skipped in 107.81 seconds.
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Help, dependency consistency and whitespace checks passed. Tests cover rejected-pool abstention, subset-only drafting, no fallback, checkpoint resume, calibration mismatch and split leakage, frozen held-out evaluation, malformed artifacts, technical failures, atomic coverage, targeted updates and transient/persistent replacement errors. Existing tests were adjusted where the new gate adds a checkpoint or correctly removes drafting calls for empty retrieval results. Intermediate Windows replacement failures were resolved with the bounded retry and dedicated failure tests.

Stage 5 verification used mocked retrieval/scoring and synthetic human-label fixtures. No project threshold was calibrated: independent reviewed calibration and held-out labels were not supplied. The separately marked real cross-encoder test remains opt-in and was not rerun; Stage 4 records its real-model verification. No Stage 5 cloud calls, model downloads, real-corpus review or index rebuild were performed. The user's `.env`, source documents, register and existing index/reports were not changed. Synthetic test outputs reside in ignored `reports/test-temp-stage5-*` directories.
