
# Stage 06 retrieval measurements — 2026-10-17

**Synthetic regression measurements only. No expert validation, legal findings,
real dossier accuracy, calibrated confidence or demonstrated retrieval gains.**

Pre-change baseline: commit `7699e40`, same branch
`feat/stage-01-foundations-telemetry`. Saved before modifying search.
Fixture SHA-256:
`8ff1b956ca73ed01a1343aa5f6e44efddfc33c959953cb12763e1be4bc51f029`.

[Baseline](../../eval/stage06_synthetic_baseline.json) and
[final comparison](../../eval/stage06_synthetic_comparison.json) retain every
case and ranked result. The fixture contains 1,016 invented chunks and seven
queries: six answerable literal-match illustrations and one unanswerable case.
Slices cover a toy clause identifier, abbreviation, multilingual terms,
negation, table terms and keyword stuffing. These expected IDs follow explicit
literal toy content; they are not expert labels or a calibration/held-out split.
No case was deleted or relabeled during implementation. The artifact hash and
case inventory are checked in tests.

| Path | Recall@5 / @10 | MRR@5 / @10 | nDCG@5 / @10 | Zero-match | Mean ms | Median ms | p95 ms |
|---|---|---|---|---|---:|---:|---:|
| Pre-change BM25Okapi | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1/7 | 8.39 | not recorded | not recorded |
| Final unchanged BM25Okapi | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1/7 | 11.25 | 9.57 | 22.66 |
| Opt-in structural BM25Plus(delta=0) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1/7 | 27.77 | 21.83 | 62.38 |
| Opt-in lexical expansion + structural BM25Plus | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1/7 | 22.26 | 22.40 | 23.11 |

Recall/MRR/nDCG are averaged over the six answerable illustrations;
unanswerable metrics are null, and the unanswerable case remains included in
latency and zero-match denominators. Duplicate returned IDs receive one vote.
Per-case/slice results are retained in JSON. Latency measures in-memory retrieval,
query tokenization/scoring/fusion and optional lexical expansion, with no
persistent BM25 cache in this harness. Structural child materialization,
immutable archive verification, disk ingestion, inference and model loading are
excluded. Final comparison ran while the offline suite was active; these seven
samples and Windows scheduling do not establish a latency improvement or a
production regression bound. Perfect toy literal-match scores are unsurprising;
there is no evidence here that the new path improves real retrieval.

All measured variants made **0 model/cloud calls, $0 cloud spend**. An actual
local Chroma create/query smoke uses deterministic fake vectors only, proving
integration mechanics rather than embedding quality. Production dense/hybrid
RRF, local LLM rerank and pinned CPU cross-encoder quality/latency comparisons:
**NOT RUN**. Relevant optional packages are already installed, but no inference
or download was needed or performed. Real OCR, browser workflow and specialist
legal review: **NOT RUN**.

## Expert gate and thresholds

`eval/gold_queries.json` is empty. Existing example datasets identify themselves
as synthetic or not human validated. Therefore:

- Expert held-out Recall@5/10, MRR, nDCG and per-slice relevance calibration:
  **NOT RUN**; no authentic judgments were substituted.
- New relevance thresholds: **NOT TRAINED / NOT VALIDATED**. No threshold or
  BM25/dense/reranker score is presented as probability or calibrated relevance.
- Default promotion: **NOT APPROVED**. Existing hybrid retrieval, planner,
  assessment evidence gate and default reranker flags remain in place.
- The separate `retrieve` command returns candidates requiring verification.
  Zero lexical matches yield `no_relevant_evidence` /
  `INSUFFICIENT_EVIDENCE`; this is not a finding of noncompliance.

For authentic comparisons, use the existing `evaluate` production experiment
pipeline with versioned human-gold cases, pinned source hashes, independent
calibration/held-out splits and all query slices. Existing strict evidence-gate
calibration verifies model/corpus/configuration identity; a declared embedding
revision is now also bound. A structural candidate score cannot silently reuse
a legacy threshold. Expert qualification and judgment quality remain human
responsibilities.

## Compatibility and limits

The new path is explicit through `retrieval-index` and `retrieve`; it does not
rebuild the user index or change assessment sources. Structural children are
exact slices of pre-existing canonical spans. They retain literal section paths
and cannot repair extraction-boundary/table errors already present in those
spans. Overlarge atomic prose remains intact and flagged; target size is a soft
bound. Child matches nominate deduplicated canonical parents; only parents
enter SourceBuffer and optional parent reranking. The child trace and parent
mapping/reranker diagnostics are separate.

Snapshots are content-addressed JSON under
`state/retrieval/<project hash>/<snapshot hash>.json`. Optional dense collections
use the snapshot hash under the same project's separate vectors directory.
No model-specific cache is reused across a changed model or declared
`EMBEDDING_REVISION`. Silent mutable-tag weight changes remain operator-managed.
Existing empty-revision manifests/configs remain readable. Saved configurations
pin empty legacy revision instead of adopting an ambient new revision.

Retrieval validates snapshots, exact child inventory, source originals,
project/collection and document versions. CLI-default current-file checks reject
changed/deleted selected documents; the API can intentionally read an archived
snapshot. Added unselected files do not expand a frozen selection. No source
selection grants legal authority. Missing/unavailable dense resources may use
the already verified lexical snapshot; source/schema/citation corruption and
cancellation do not become fallbacks. Reranker timeouts retain fused order under
the existing synchronous/cooperative transport/CPU deadline limitations. Shared
lazy run scopes now also bound standalone programmatic multi-query search and
multi-batch structural builds; budget exhaustion cannot reset per batch.

JSON/Chroma are not an atomic cross-store publication. Failed dense candidate
writes remove only that newly created collection; a later JSON failure can leave
an unreachable collection, with previous snapshots retained. No automatic GC or
distributed concurrent-build transaction is implemented. Snapshot
reconstruction/original hashing adds IO; the toy harness does not benchmark it.
Selected cached BM25 data is bounded to four inventories; expanded plans to 64.
Snapshots are bounded to 50 MiB, 2,000 manifests and 100,000 parent/child records.

Rollback: revert the Stage 06 commit while retaining original archives,
profiles/registry/applicability state, assessment histories and
`state/retrieval`. Earlier code ignores the new optional index. Restore the
previous explicit embedding model/revision when using earlier vectors; preserve
this reader or export reports with new configuration identities first. No data
deletion or rollback was performed.

Next stage: `07_EVIDENCE_AND_CITATION_AUDIT.md`; not started.

Final offline gate: **717 passed, 1 optional real-model skipped** (144.44s); focused final retrieval suite: **78 passed** (51 new cases; 8.25s). Compile, CLI, AST and whitespace checks passed. **STAGE_06=PASS** for implementation; expert/default promotion gates remain unrun as documented.
