# Stage 3 verification

Verified on 2026-10-13 on `qmatrix-impelmantion`, based on Stage 2 commit `59de554`. Implementation commit: see Git history for "Add bounded query planning and provenance-aware retrieval".

## Behavior

- Reviews keep the original requirement query and add up to three deduplicated artifact, process/test and explicit profile qualifier searches. Deterministic templates use requirement text and supplied device name/intended purpose. Optional local-model planning selects menu IDs only; invalid JSON, unknown IDs or model failures record a deterministic fallback. Planning is a retrieval intent, not a legal conclusion. Storage failures propagate rather than becoming fallbacks.
- The shared `search.retrieve_candidates` API supports dense, BM25 and hybrid modes. `hybrid_search` remains a single-query compatibility wrapper. Each backend returns at most 12 candidates per query. Unique chunk ranks are fused within each query, then across unique query lists using reciprocal-rank fusion (constant 60). Raw backend scores are not summed. Ties use chunk ID; the merged pool is capped at 30 before optional reranking once against the original query. Final `k` accepts 1..30.
- BM25-only retrieval never calls embeddings. A four-entry in-memory cache retains filtered corpus tokenization and BM25 construction by database/collection, legal/device kind and manifest fingerprint. Changed manifests produce new cache entries. Returned records copy metadata so consumers cannot mutate cached corpus records. The backend filter and local corpus-membership/kind/source checks both apply.
- Schema-2 assessment sections add optional `query_plan` and validated `retrieval_trace` fields; old files remain readable. Plans, backend/query ranks, merged/selected IDs and fallback reasons survive checkpoints, finding history and JSON compatibility exports. The complete retrieved union has immutable source snapshots; model presentation and cited raw spans remain separate. Targeted updates retain unaffected findings/timestamps/revisions. Resume reuses completed query/retrieval checkpoints without extraction or repeated retrieval.
- Query/planner settings and implementation identity invalidate planning onward; retrieval budgets invalidate retrieval onward. Optional LLM planner model/context identity also participates in query dependencies. Existing historical snapshots are retained. Single-query compatibility mode omits the multi-query trace.
- `.env.example` documents validated settings and existing model/legal defaults. README distinguishes multi-query reviews from single-query `ask` and the separate evaluation implementation. `pytest.ini` confines default discovery to `tests/`, avoiding generated report/test-output folders.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage3-baseline
# 116 passed before changes
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage3-release -p no:cacheprovider
# 143 passed after changes
.\.venv\Scripts\python.exe main.py --help
git diff --check
```

Baseline: no pre-existing test failures. The final suite includes 27 new deterministic cases for expansion-only matches, duplicate query/backend votes, query/backend provenance, both corpus filters, manifest caching, BM25 without embeddings, stable fusion, bounded disjoint candidate pools, reranking once, invalid configuration, planner scope/fallback, storage-error propagation, persisted planner failures, checkpoint resume, targeted update preservation, dependency invalidation and immutable cache records. Existing tests deliberately set single-query compatibility mode where their retrieval mock expects one call; their existing assertions remain.

Intermediate failures were confined to new synthetic fixtures with invalid text-passage block/page metadata; those fixtures were corrected. A repository-wide discovery attempt encountered 19 Windows permission errors scanning old ignored test-output folders under `reports/`, rather than application test failures. Explicit `tests/` discovery passed; the added `pytest.ini` also makes the normal command use that scope. Pytest's cache plugin was disabled for final verification because the sandbox can deny access to retained `.pytest_cache` folders.

## Preservation and limits

Only mocked/synthetic workflow tests were run. No live inference, real-corpus review/evaluation, extraction, migration, model download or index rebuild/deletion was performed. The user's `.env`, original documents, device profile, register, manifest, vector index and existing assessment snapshots were not modified. Dedicated ignored test folders contain synthetic outputs. The unrelated untracked `how HEAD` file was excluded from the commit.

The existing `evaluate` command retains its separate single-query retrieval implementation; these tests establish deterministic behavior, not measured recall improvements or performance guarantees. Model tags remain dependency identities rather than verified weight digests. Raw quotation validation establishes provenance/context membership, not entailment, applicability, complete legal coverage or conformity. Stage 4 rerankers, calibrated evidence gates and independent semantic review remain future work.
