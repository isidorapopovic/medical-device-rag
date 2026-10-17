# Stage 8 verification

Verified on 2026-10-13 on `qmatrix-impelmantion`, based on Stage 7 commit `1e5da8d608b73e3e4d5a51f3febb27671e58670c`. Implementation commit: see Git history for "Stage 8: Evaluate production pipelines with held-out grounding metrics".

## Implemented behavior

- `evaluation.evaluate` delegates to production comparison experiments. All retrieval methods use `search.retrieve_candidates`, its shared BM25 cache, corpus filters, bounded candidate API and two-level RRF. Multi-query uses the production planner; reranking uses the production backend implementation. Methods name their backend explicitly instead of reporting a cross-encoder under `hybrid_reranked`.
- Complete experiments invoke the six-role review against a selected existing requirement under a fresh distinct assessment ID. They retain the full register and truthful partial state, use gate/reviewer/repair/citation policy, and leave the user's latest compatibility report untouched. They never extract requirements or rebuild an index.
- Gold supports explicit `answerable=false` with `relevant=[]`. Malformed positives do not become negatives; no-positive recall/MRR/nDCG/hit rate are null with separate denominators. Passage labels are independent: useful partial passages can exist without a fully answering gold label. Human gold requires reviewer validation, matching corpus hashes and a legal-version label. Synthetic/unverified/legacy data remain explicitly identified.
- Questions and requirement IDs cannot receive duplicate votes or leak across calibration/held-out splits. Held-out aggregates exclude calibration cases. Ineligible complete-pipeline cases are listed as exclusions. Every method records 12 candidates per query/backend and a 30-candidate merged cap; single-query versus up-to-four-query search budgets are reported as a difference.
- Outputs track top-k retrieval metrics, candidate recall before reranking, exhaustively labeled passage precision and annotation coverage, gate evidence retention versus final finding retention, unanswerable abstention, raw citation validity, published citation validity and reviewer inventory coverage. Execution/scoring/reviewer failures remain failures, not successful abstentions. Gate mode/reason/fingerprint and strict validation outcome remain visible.
- Human claim support and contradiction misses use a separate offline adjudication file bound to the frozen evaluation, assessment revision, claim revision and context hash. Every published claim case/ID must be labeled exactly once. No model verdict becomes human gold. Evaluation uses opaque claim-ID aliases to prevent model-chosen IDs from leaking source prose; private canonical IDs are preserved.
- Assessment stage events now record finite elapsed seconds. Evaluation reports median/p95 stage/method timing, failure counts, recovered model-call failures, Python allocation peak and optional process RSS/lifetime peak with explicit measurement limitations. It records libraries/platform, corpus/model/prompt/planner fingerprints, token/context limits, score transformations and retrieval parameters. Ollama model digests/device remain explicitly unverified; pinned cross-encoder identities remain recorded.
- Optional validated `OLLAMA_NUM_GPU=0` requests zero GPU layers in generation, embedding and LLM reranking; blank preserves automatic selection. Actual server execution must be verified before claiming CPU-only performance. Existing supported cross-encoder setting names and the fixed one-repair bound are documented rather than pretending proposed aliases are read.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage8-baseline -p no:cacheprovider --tb=short
# Baseline: 274 passed, 1 skipped in 138.44 seconds; no pre-existing failures.
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage8-final-verified -p no:cacheprovider --tb=short
# 300 passed, 1 skipped in 258.06 seconds before the final independent-passage-label case.
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage8-release-complete -p no:cacheprovider --tb=short
# Final: 301 passed, 1 skipped in 248.46 seconds.
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe main.py evaluate --help
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Help, dependency consistency and whitespace checks passed. Twenty-seven new synthetic cases cover the six production comparisons; none/LLM gate policy; BM25 without embedding or reranking; negative cases and undefined denominators; partial relevance versus answerability; split/requirement leakage; held-out-only aggregation; failure/abstention separation; genuine quotes rejected semantically; human adjudication bindings; duplicate-output protection; redacted artifacts and model-chosen claim IDs; and CPU options reaching all three Ollama call paths. Existing retrieval comparison tests now patch production providers and assert the explicit `hybrid_llm` label. The separately marked real cross-encoder test remains opt-in/skipped.

Read-only real preflight: `inspect` passed (exit 0); hybrid device `explore` failed before inference (exit 1) because the current files differ from the index manifest. Inspection output is kept in an ignored private log. The real gold set contains 0 cases, the register 15 requirements and the manifest 3 sources. Real accuracy, latency, native model peak memory and human claim metrics were not measured; see [the honest evaluation report](stage8_evaluation_report.md). No real review was created, no fake calibration was added, and `.env`, documents, the existing register/index and old reports were preserved. Synthetic output and private preflight metadata reside in ignored `reports/test-temp-stage8-*` and `reports/stage8-preflight/` directories.
