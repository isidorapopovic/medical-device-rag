# Stage 06 — Retrieval improvements with objective benchmarking

## Goal
Extend existing BM25 + Chroma hybrid and optional local rerank; preserve simple CPU path.

## Implementation
1. Establish fixed query/expected-span retrieval fixture set from available **expert-labeled** cases; keep synthetic toy datasets separate and clearly marked. Save existing results as baseline before tuning.
2. Implement legal-aware and device-aware structural chunking with parent-child linkage and stable spans; avoid splitting clauses/tables blindly. Maintain indexes per project, collection, document revision, embedding model/version.
3. Multi-query expansion (0 or 1 bounded LLM call per requirement, configurable, cache query results): regulatory wording, document synonyms, negation/alternate terms. Lexical expansion fallback if model unavailable. Cap queries at 4, candidate pools/char budgets. Never let query generation fabricate source evidence.
4. Preserve BM25, dense, hybrid/RRF modes. Add optional CPU cross-encoder behind feature flag; compare against existing local LLM rerank on representative cases; gracefully skip if weights missing/offline. Rerank only fused top-K.
5. Add relevance thresholds trained/validated on held-out labels and query slices. `no_relevant_evidence` returns abstention, not confident negative. Scores from BM25, dense and reranker are not directly calibrated probabilities.
6. Track per-query timings, results, dedup and source version. No model-specific embedding cache reuse after a model change.

## Tests
- Exact clause IDs; abbreviations; multi-language text; adversarial keyword stuffing; duplicated chunks; legal vs device corpus contamination; empty/huge query; missing embedding model; corrupted Chroma DB; reranker timeout; stale/deleted docs; 1000+ chunks performance.
- Regression compare Recall@5/10, MRR, nDCG, latency, zero-match rate, cost; forbid cherry-picked eval case deletion.

## Gate
New retrieval defaults only if improves held-out metrics without unacceptable latency/cost regressions; otherwise keep current hybrid. BM25-only remains fully usable offline.
