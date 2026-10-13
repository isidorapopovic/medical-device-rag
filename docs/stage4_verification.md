# Stage 4 verification

Verified on 2026-10-13 on `qmatrix-impelmantion`, based on Stage 3 commit `f2b31a4`. Implementation commit: see Git history for "Stage 4: Add local reranker backends and traced CPU cross-encoder scoring".

## Implemented behavior

- Added `none`, `llm` and `cross_encoder` selection. `--rerank` still forces the Ollama LLM, including when another backend is configured. Explicit `--rerank-backend` precedes the command and is mutually exclusive with that flag. A nonblank `RERANK_BACKEND` overrides the legacy environment boolean. Existing direct `rerank_passages` calls retain their LLM default. There is no fallback to a different backend on dependency, model-loading, tokenization or scoring failure.
- `requirements-rerank.txt` is separate from the minimal install. The tested Windows/Python 3.13 stack is Sentence Transformers 5.1.2, Transformers 4.57.1, PyTorch 2.8.0, safetensors 0.6.2 and tokenizers 0.22.2. `pip check` passed. Optional dependencies are never imported by help, `none` or LLM scoring.
- The initial public model is `BAAI/bge-reranker-base`, pinned to commit `2cfc18c9415c912f9d8155881c133215df768a70`. Explicit provisioning uses `python -m mdr_rag.download_reranker`; inference only resolves existing local files. Windows provisioning uses a separate ordinary-file directory and a model/revision marker, avoiding symlink privileges and same-file copying. Missing/incomplete/mismatched snapshots fail explicitly. The weights SHA-256 observed in the real test was `ced967c45fd1902eb92716c9ceeca7c95a936770ea9db611f5a841b926e33fbd`.
- Lazy loading is protected by a process lock and cached per fingerprint. Fingerprints include revision, actual weight/tokenizer/config hashes, installed library versions, preprocessing implementation, batching/token settings, CPU float32, four CPU threads, eager attention and raw-logit score transformation. Retrieval dependencies include this identity; LLM prompt identity hashes the actual LLM scoring implementation.
- At most 30 candidate pairs are scored, in batches of four by default. Scores use the original requirement query plus explicitly supplied, unverified device name/intended purpose; expansion queries never contribute separate maximum scores. Sorting returns deep copies, preserves IDs/text/hashes/provenance, and retains original fused order for equal scores. Finite scalar scores and a complete unique candidate/score mapping are required.
- The combined pair limit is 512 tokens, including special tokens. A query prefix of up to 128 tokens is retained, reserving space for at least one passage token; only the passage is then right-truncated. Fast-tokenizer offsets map directly to original parent-chunk character positions. Query bounds, token count, truncation flags and encoded-input hashes are retained. Long original queries or appended qualifiers can truncate; diagnostics expose this limitation. The exact prepared tensors go to the CPU model loaded through `CrossEncoder`, rather than being tokenized a second time by `predict()`.
- Canonical model-call traces record inputs before scoring and completed/failed outcomes. Retrieval traces and finding history retain scores and original candidate provenance; compatibility JSON adds score diagnostics and `rerank_citation_coverage`. A quote outside the cross-encoder token-offset envelope is explicitly not marked seen. LLM text is recorded as submitted but actual token visibility remains unverified. These are provenance facts, not semantic support or calibrated confidence.
- Single-query reranked reviews use the shared candidate API too. `ask` and evaluation respect selected backends. Evaluation retains its separate single-query retrieval implementation and `hybrid_reranked` method name; its reranker pool is capped at 30 and its JSON records actual backend/model/score identity. The BM25 cache also includes collection identity, avoiding reuse after collection replacement or between independent test collections.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage4-before -p no:cacheprovider
# Baseline: 141 passed, 2 Windows file-replacement permission failures.
.\.venv\Scripts\python.exe -m pytest tests/test_report_state.py::test_interrupted_run_resumes_from_retrieval_checkpoint tests/test_report_state.py::test_partial_legacy_resume_integrates_register_without_double_counting -q --basetemp reports/test-temp-stage4-baseline-retry -p no:cacheprovider
# Both passed before changes to the existing application paths.
.\.venv\Scripts\python.exe -m pip install -r requirements-rerank.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m mdr_rag.download_reranker
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage4-final -p no:cacheprovider
# 175 passed, 1 deliberately skipped opt-in real-model test.
$env:RUN_CROSS_ENCODER_SMOKE='true'
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python.exe -m pytest tests/test_reranking.py -m real_model -q --basetemp reports/test-temp-stage4-real-final -p no:cacheprovider
# 1 passed; other cases deselected.
.\.venv\Scripts\python.exe main.py --help
git diff --check
```

The 32 new unit cases use fake scoring, fake tokenization or mocked model responses. They cover stable copied ranking, preserved identity/hash/provenance, NaN/infinite/missing/duplicate/invented scores, dependency/download errors, no network/Ollama calls, lazy loading, all backend choices, legacy flag precedence, CLI selection, persisted input/score/failure traces, both truncation types, budgets, model/library fingerprints, citation visibility, dependency invalidation, help with optional imports blocked, ordinary-file provisioning and invalid provisioning markers. The separately marked real test checks actual CPU float32 parameters, finite scores, truncation and both 3- and 30-pair workloads, while blocking socket connections.

The two initial baseline failures were `PermissionError` during atomic Markdown replacement in existing interrupted-resume and legacy-resume tests; both passed on immediate isolated retry. They are recorded as environmental baseline failures, separately from regressions. An intermediate full run exposed a synthetic-manifest cache collision; adding collection identity fixed it, and the affected existing test passed. Provisioning initially encountered Windows symlink privileges and a same-file copy; the corrected explicit helper completed successfully. No errors caused an automatic backend switch.

## Real-model observations

Synthetic smoke metrics are saved locally in ignored `reports/stage4-real-smoke/metrics.json`, including library/model/artifact identities, raw scores, tokenizer ranges and truncation. Initial observations: model hashing/import/loading 31.13 seconds; 3 pairs 3.71 seconds; 30 mixed-length pairs 27.99 seconds; RSS after scoring 1,334,632,448 bytes; process peak RSS 1,357,340,672 bytes (about 1.26 GiB). The final smoke passed against the completed implementation and refreshed that artifact: loading 19.58 seconds, 3 pairs 3.56 seconds, 30 pairs 28.42 seconds, final RSS 1,333,514,240 bytes and peak RSS 1,356,783,616 bytes. These are single-process observations, not production throughput/recall measurements or guarantees. Peak process RSS includes imports/loading; it is not incremental model memory. Candidate lengths, hardware, caching and competing processes affect results. No default-backend change was made.

Model pin and API references: [published model revision](https://huggingface.co/api/models/BAAI/bge-reranker-base), [model card](https://huggingface.co/BAAI/bge-reranker-base), [versioned CrossEncoder implementation](https://github.com/UKPLab/sentence-transformers/blob/v5.1.2/sentence_transformers/cross_encoder/CrossEncoder.py).

## Preservation and limits

The optional packages were installed in the existing virtual environment, and public model files were explicitly downloaded into ignored `reports/reranker-cache`. No user documents were transmitted. Real inference used only synthetic passages with networking disabled; no live Ollama generation/embedding, real-corpus review/evaluation, extraction, migration or index rebuild/deletion occurred. The user's `.env`, documents, profile, register, manifest, vector index and existing assessment snapshots were not changed. The unrelated untracked `how HEAD` file is excluded from the commit; model files, reports and virtual-environment files are also excluded.

Raw logits are relevance signals, not evidence sufficiency or compliance probabilities. Sigmoid transformation would not supply calibration. Token-offset envelopes describe retained source ranges conservatively; tokenizer normalization can remove characters within them. Historical reports render saved diagnostics without loading a current model. Ollama model tags retain the existing limitation that they do not pin weight digests. Evidence gates, calibrated thresholds and independent semantic auditing remain later stages.
