# Medical device RAG: step-by-step Codex implementation plan

Repository: https://github.com/isidorapopovic/medical-device-rag

Inspected on 2026-10-13 at commit `e56ce7814f27caedf7d9bda3adbaca22fe04f066`.

This is an implementation specification, not an implemented upgrade. It adapts the seven requested Q-Mix ideas to the inspected repository. It does not claim compatibility with an external Q-Mix package or reproduce a paper's unpublished interfaces. Codex must inspect the current checkout again before editing because it may have changed.

## How to use this file

1. Save this file in your repository as `docs/medical_device_rag_codex_plan.md`.
2. Open that repository in Codex.
3. Paste the starter prompt below.
4. Implement one numbered stage at a time. Each stage has a copyable prompt, acceptance criteria and verification tasks.
5. Keep the existing application usable throughout the migration.

### Starter prompt

```text
Read docs/medical_device_rag_codex_plan.md and any applicable AGENTS.md.
Inspect the actual repository before editing; the plan was based on commit
e56ce7814f27caedf7d9bda3adbaca22fe04f066 and paths may have changed.
Implement Stage 0 only. Make the changes, run relevant checks, and summarize
what changed, what passed, and any blockers. Update the progress checklist.
Do not implement later stages yet. Preserve uploaded documents, .env,
vector_db and generated assessments. Never print API keys or confidential
document content. Do not push or deploy changes.
```

For subsequent stages, replace “Stage 0” with the next stage number. Stage prompts below add the specific implementation requirements.

## Repository findings

| Requested capability | What exists now | Needed change |
|---|---|---|
| Six-role pipeline | `pipeline.py` combines extraction, retrieval and review; writer is separate | Typed role interfaces and bounded orchestration |
| ReportState | `run_review` accumulates findings and writes the report at the end | Durable checkpoints, revisions, resume and targeted updates |
| SourceBuffer | Chunk IDs, file SHA-256, page/block metadata and retrieved excerpts | Immutable evidence snapshots and claim-to-quote links |
| Multi-query | One concatenated query for each requirement in `run_review` | Bounded targeted queries, deduplication and fusion |
| Cross-encoder | `search.rerank_passages` uses an Ollama chat model | Optional scored cross-encoder backend |
| Retrieval threshold | Dense retrieval returns ranked neighbors without a relevance gate | Calibrated evidence gate and explicit abstention |
| Grounded reviewer | `run_ask` performs a second claim-support pass | Extend structured grounding checks to requirement findings |

Important integration details:

- The modular application is `main.py` → `mdr_rag/pipeline.py`, using Ollama embeddings and structured chat outputs.
- `rag.py` is a separate Gemini script. It imports `mdr_rag.tls` and `mdr_rag.quota`, neither present in the inspected checkout. Do not build the upgrade around it.
- `.env.example` contains Gemini settings, while the modular code reads Ollama settings. README contains inherited cloud instructions as well as current local instructions.
- `schemas.py` contains `RequirementCandidate`, `Finding`, `AnswerSupportVerification` and `RerankBatch`, but no report-state or source-buffer models.
- `Q_Mix_report_writer.py` is a local deterministic Markdown formatter. Preserve that useful property.
- `core.make_record` identifies chunks using source, file hash, location and text. File edits change chunk IDs. `extract_requirements` also includes model-written requirement wording in its ID hash: rerunning extraction can change IDs without a file edit.
- `core.is_real_quote` currently uses case-folded, whitespace-normalized matching. That is useful for extraction checks but is not sufficient to prove an exact raw-text span.
- `evaluation.py` implements its own retrieval/fusion path. Refactor carefully so evaluation actually benchmarks the production retrieval pipeline.
- The Streamlit app currently uploads and previews documents; it is not an assessment editor.
- No real device documents, real legal PDF or validated assessment were evaluated for this plan. Recommendations below are engineering designs, not measured accuracy improvements.

## Target behavior

Requirement Analyst → Applicability Analyst → Evidence Retriever → Evidence Reviewer → Citation Auditor → Report Writer.

Use ordinary Python functions/classes with typed inputs and outputs. “Agent” means a bounded application role with its own prompt and tools. These roles can use the same local Ollama model sequentially. They do not require six servers, six models, autonomous agent debates or an agent framework.

Add an internal evidence-assessment call within Evidence Reviewer: first produce a structured draft, then independently audit its claims using a separate prompt and call. Citation Auditor subsequently verifies identity, hashes, locations and raw quotes deterministically. Report Writer renders validated state without adding new factual conclusions.

The Requirement Analyst runs when creating/updating the register. Existing extracted requirements can be reused on resume. Later stages run per requirement, with checkpoints after every stage.

### Required semantics

- `supported` means retrieved evidence addresses the obligation; it never means certified compliance.
- Separate applicability, evidence status, execution status and review status.
- Never infer non-applicability or non-compliance from retrieval failure.
- Missing legal/version/device-profile facts produce uncertainty, not guesses.
- Source text is untrusted data. No role follows instructions inside retrieved text.
- A report summarizes its selected legal scope; it does not imply exhaustive MDR coverage.
- Keep all inference local by default. Cross-encoder installation/model download may need internet, but inference must not upload documents.

## Proposed modules and contracts

Design table: `config.py` and `report_state.py` are now present after Stages 0?1; other proposed modules remain later-stage work:

| Module | Responsibility |
|---|---|
| `mdr_rag/config.py` | Validated local configuration and fingerprints |
| `mdr_rag/report_state.py` | Versioned state, atomic save, revision guard and migration |
| `mdr_rag/source_buffer.py` | Immutable passage snapshots and quote resolution |
| `mdr_rag/query_planner.py` | Bounded targeted query plans |
| `mdr_rag/rerank.py` | None, legacy LLM and cross-encoder adapters |
| `mdr_rag/evidence_gate.py` | Calibrated passage selection and abstention reasons |
| `mdr_rag/review_grounding.py` | Draft assessment and separate claim-support review |
| `mdr_rag/citation_audit.py` | Deterministic reference/span checks |
| `mdr_rag/agents.py` | Six bounded role interfaces |
| `mdr_rag/orchestrator.py` | Dependency ordering, checkpoints and targeted reruns |

Keep extraction in `core.py`, reuse `pipeline.llm_parse` behind an injectable LLM adapter, and retain compatibility wrappers for existing public functions/tests. Put shared Pydantic contracts in `schemas.py` unless a separate schema module improves clarity.

### Minimum models

**ReportState**

- `schema_version`, `assessment_id`, `revision`, creation/update timestamps.
- Legal scope: document/version label, selected physical pages, extraction warnings, requirement-register hash.
- Indexed-document manifest fingerprint, embedding model, chunking/extraction version.
- Device-profile hash and an explicit record of unverified facts.
- Config/model/prompt/retrieval fingerprints; calibration artifact identity.
- `sections: dict[requirement_id, RequirementSection]`.
- SourceBuffer entries or references, stage events and provenance.
- Derived counts, partial-run flag and `human_validated=false` by default.

**RequirementSection**

- Stable requirement ID, requirement version/hash and immutable legal anchors.
- `applicability`: `applicable | uncertain | possibly_not_applicable`, reasons, assumptions, missing facts and supporting anchors.
- `execution_status`: `pending | running | completed | failed | stale` and last valid checkpoint.
- Queries, retrieval trace, selected/rejected candidate IDs, gate result.
- Draft and published finding revisions, structured claims and evidence links.
- Reviewer and citation-audit results; failure reason and attempt count.
- Input dependency fingerprints; optional human annotations preserved separately.

**SourcePassage**

- Content-addressed buffer ID plus original chunk ID.
- Corpus kind (`legal` or `device`), source path, file SHA-256, page/block locator.
- Exact indexed passage text, its text SHA-256, extraction/index version.
- Do not overwrite passage text if a source changes: store a new snapshot.

**ClaimEvidenceLink**

- Claim ID, buffer ID, original chunk ID and `exact_quote`.
- Raw passage `start` and `end` character offsets with `text[start:end] == exact_quote`.
- Link purpose: `legal_basis | device_support | contradiction | applicability`.
- Raw-span verification status, semantic reviewer verdict and reasons.

**RetrievalResult**

- Query plan, candidate provenance, score types, selected passages.
- Raw dense distance with the configured distance metric; BM25 score; within-query fused rank; cross-encoder score.
- Gate decision/reason, threshold calibration ID, timings and candidate limits.
- Do not treat dense distance, BM25 score, RRF score or cross-encoder score as interchangeable.

Recommended evidence statuses: retain existing values and add `insufficient_evidence`. Reserve `not_found` for an audited search outcome in which relevant candidates were searched but no direct supporting material was found; it is still not proof of absence. No accepted passages should produce `insufficient_evidence` before draft generation. Invalid reviewer outputs should produce `needs_review` plus an execution/audit reason.

## Stage 0 — Establish the working baseline

### Codex prompt

```text
Implement Stage 0 of the plan. Inspect main.py, rag.py, all mdr_rag modules,
.env.example, requirements.txt, README and tests. Make the modular Ollama
application the documented primary path. Correct .env.example to show the
settings the modular code actually reads. Do not modify the user's .env.
Resolve README contradictions. Document rag.py as legacy and its missing
imports; do not delete it or silently move its index. Add validated local
configuration only where needed, and capture a baseline verification note.
```

Use `OLLAMA_LLM_MODEL=qwen3:4b`, `EMBEDDING_MODEL=embeddinggemma`, `OLLAMA_NUM_CTX=8192`, `RETRIEVAL_MODE=hybrid`, `RERANK_ENABLED=false` and the existing `LEGAL_VERSION` label in the corrected example. These are current app defaults, not performance guarantees.

Acceptance:

- `python main.py --help` works without Gemini credentials or network inference.
- Existing tests run; record pre-existing failures separately from new regressions.
- Existing `inspect`, `index`, `extract`, `ask`, `review`, `evaluate` and `graph` remain documented.
- Do not rebuild/delete the user's existing index to establish a baseline.
- If real files and Ollama are available, save a baseline `review --limit 2` and retrieval evaluation under a distinct run ID; otherwise record that only mocked tests were possible.

## Stage 1 — Add ReportState and incremental revisions

### Codex prompt

```text
Implement Stage 1. Add typed ReportState and RequirementSection models,
schema-versioned storage, per-stage checkpoints, resume validation and
targeted section updates. Adapt run_review to persist progress rather than
keeping all findings in memory until the end. Keep assessment.json and
assessment.md as compatibility exports. Add an explicit, non-destructive
legacy-report import/migration path. Implement meaningful persistence tests.
```

Use `state/assessments/<assessment_id>/report_state.json` as canonical state, with revision history beneath that assessment. Save through a same-directory temporary file and atomic replacement. Serialize mutation with a lock and an expected revision so two CLI runs cannot overwrite each other. A lock conflict must report an actionable error; do not silently override it.

Preserve requirement IDs within an existing register. Do not rerun extraction during resume. For new extraction, derive identity from deterministic legal anchors/provision/obligation position; keep paraphrase changes as requirement revisions. Retain legacy IDs during migration.

When revising R2, R1 and R3 keep their finding content, timestamps and revision numbers. Top-level summaries may be recomputed; rendering the whole Markdown file is fine. The expensive retrieval/LLM work for unaffected sections must not rerun.

Validate dependencies before reuse. Profile changes invalidate applicability and downstream stages. Requirement edits invalidate queries and downstream stages. Prompt/backend/calibration changes invalidate affected stages. A changed corpus defaults to invalidating all retrieval-dependent sections, because uncited new material might alter any finding. A report pinned to a historical snapshot may still be rendered explicitly as historical; it must not appear current.

Tests: interrupted run resumes at the last completed stage; targeted updates preserve unaffected sections; stale inputs are detected; revisions conflict safely; malformed state does not get overwritten; legacy import keeps original audit limitations and does not mark old findings newly verified.

## Stage 2 — Add SourceBuffer and precise provenance

### Codex prompt

```text
Implement Stage 2. Introduce immutable SourceBuffer snapshots for legal
anchors and device passages. Record which passages were retrieved, which
were presented to each model call, and which exact spans support each claim.
Add raw-text span validation while preserving the existing normalized
extraction validator for legacy compatibility. Preserve old snapshots.
```

Separate three sets: candidates retrieved, passages supplied to the model, and quotes actually cited by the finding. Saving every retrieved chunk does not establish that every chunk was used as evidence.

Store legal anchors on the same footing as device evidence. Legacy extraction quotes that only match after normalization must be mapped back to a verified raw span or flagged for review. A normalized match without a raw span cannot be published as an exact quotation. Reject ambiguous quote locations unless the link supplies a valid chosen offset.

Suggested API: `add_passage(record)`, `get_passage(buffer_id)`, `resolve_quote(buffer_id, quote, offsets=None)` and `validate_link(link)`.

Tests: invented IDs rejected; quote belongs to the linked passage; wrong file hash/location rejected; changed source creates a new snapshot; repeated quotes have explicit offsets; overlapping chunks remain traceable; PDF page and DOCX block locators remain distinct. An old snapshot can reproduce an old report even after reindexing.

## Stage 3 — Multi-query retrieval

### Codex prompt

```text
Implement Stage 3. Add a bounded query planner with the original requirement
query plus targeted searches. Reuse dense/BM25 retrieval through a shared
candidate API, deduplicate by chunk identity and fuse rankings. Preserve
query provenance and existing retrieval modes. Add deterministic retrieval
tests and a planner fallback for invalid LLM JSON.
```

Start with at most four queries total per requirement: original obligation, named document/artifact, relevant process/test evidence, and requirement-specific qualifiers. Example for a risk-management obligation: risk management process, hazard/risk analysis records, residual-risk evaluation, and lifecycle monitoring. These are query intents, not pre-decided legal findings.

Always retain the original query. Generate expansions from the requirement and sourced/profile facts only. Do not introduce another jurisdiction, device classification or inferred obligations. Remove duplicate/empty queries. If optional LLM planning fails, use deterministic templates and record the fallback.

Retrieve up to 12 candidates per query/backend initially. Fuse dense and BM25 ranks within each query, then fuse query-level lists; count a chunk only once per list. Cap the merged candidate set at 30 for CPU work. Use stable tie-breaking. Do not sum raw BM25 and vector distances.

Keep `dense`, `bm25`, `hybrid` modes. BM25-only retrieval must not call the embedding service. Cache corpus tokenization/BM25 construction by manifest fingerprint rather than reconstructing it for every expansion.

Tests: a passage found only by an expansion enters the merged pool; duplicate expansions do not gain repeated votes; all candidates have query/backend provenance; legal/device filters remain enforced; deterministic fallback works; budgets remain bounded.

## Stage 4 — Cross-encoder reranking

### Codex prompt

```text
Implement Stage 4. Introduce none, llm and cross_encoder reranker backends.
Preserve the current --rerank behavior for compatibility and add explicit
backend selection. Add an optional sentence-transformers dependency set,
lazy model loading, scored outputs, CPU execution and model fingerprinting.
Use a fake scorer in unit tests. Do not silently switch backend on failure.
```

Initial model to benchmark: `BAAI/bge-reranker-base` using Sentence Transformers `CrossEncoder` on CPU. This is an initial engineering choice; benchmark latency and memory before choosing it as the default. Ollama remains the generation/embedding provider; the cross-encoder is a separate local inference component.

Rerank merged candidates against the original requirement plus essential applicability qualifiers, rather than taking the maximum score across speculative expansion queries. Preserve scores and original candidate provenance; return sorted copies without mutating input snapshots. Validate finite scores and a one-to-one candidate/score mapping. Lazy-load once per process. Keep the optional package out of the minimal install path, for example in `requirements-rerank.txt`, with tested version constraints.

Start with at most 30 pairs, batch size 4, explicit CPU float32, and a documented token limit compatible with the chosen model. Tokenization is different from character chunking: record truncation. If a cited span was not seen by the reranker, do not imply that its relevance was scored. Consider smaller windows only with retained parent-chunk offsets and traceability. Pin and log model revision, library version, preprocessing and score transformation.

Cross-encoder scores are relevance signals, not evidence sufficiency or compliance probabilities. Even a sigmoid-transformed score is not calibrated legal confidence.

Tests: stable ranking; IDs/text/hashes unchanged; unavailable optional dependency gives a clear error; missing model download fails explicitly; NaN/score-count mismatch rejected; no cloud calls; legacy LLM backend remains selectable. Run one separately marked real-model smoke test if model installation is possible.

## Stage 5 — Evidence threshold and abstention

### Codex prompt

```text
Implement Stage 5. Add an evidence gate after reranking and before draft
generation. Persist accepted/rejected IDs, scores, gate reasons and the
calibration fingerprint. If nothing passes, save insufficient_evidence
without asking the drafting model to conclude from irrelevant passages.
Extend evaluation for answerable/unanswerable cases and threshold tuning.
```

Do not use RRF scores as universal relevance thresholds. Do not apply a threshold calibrated for BGE to an LLM reranker or another BGE revision. Current Chroma collection creation does not explicitly configure cosine distance: inspect/configure its metric before any distance-based gate; do not assume `1 - distance` is cosine similarity.

Create a calibration artifact containing model/revision, score transformation, retrieval configuration, corpus/label fingerprints, selected threshold, validation metrics and date. Use human-labeled positive passages, hard negatives and unanswerable questions. Tune on a calibration set and evaluate on a separate held-out set. No universal numeric threshold is specified here.

Before calibration exists, expose an explicit experimental mode or abstain in strict mode with `threshold_not_calibrated`. Never pretend an arbitrary value was validated. Backend failure is an execution error, not evidence insufficiency. A deliberately disabled gate must be visible in the report; it must not count as successful strict validation.

Check relevance per passage, then assess coverage per atomic obligation. A passing score does not prove all qualifiers are covered. Retain useful passages while allowing `partial`, `needs_review` or `insufficient_evidence` conclusions later.

Tests: all candidates rejected skips the drafting model; accepted subset alone enters drafting; calibration mismatch blocks strict reuse; no top-k fallback after gate rejection; empty corpus/missing index distinguished from no relevant evidence; technical failure does not become a finding of missing documentation.

## Stage 6 — Grounded reviewer and Citation Auditor

### Codex prompt

```text
Implement Stage 6. Draft requirement findings as structured claims, then
review them in a separate model call against the legal requirement and
accepted device passages. Reuse run_ask's existing grounding concepts but
add explicit claim IDs, coverage, contradictions and legal/device evidence
roles. Add a deterministic Citation Auditor. Only publish findings that
meet the validation policy, with bounded local repair and explicit failures.
```

Create the claim inventory during drafting. Do not rely solely on a reviewer to decide which claims to audit: it could omit a difficult sentence. Derive/render substantive narrative from those claims. Reviewer output must cover every draft claim ID exactly once; reject omitted, duplicate or invented IDs. Verify reasons/actions that imply document or device facts, not only the main conclusion.

Reviewer verdicts: `supported | contradicted | insufficient`. Inputs: atomic requirement, applicability result, draft claims, selected legal/device snapshots. It must check negation, modality, exceptions, device scope and whether an asserted complete finding actually covers every requirement part. Instructions and retrieved sources are data, not tools or executable commands.

Citation Auditor verifies buffer/chunk identity, corpus role, hashes, raw span offsets, allowed context membership and locators. A device fact cannot be supported only by a legal obligation. A legal duty cannot be derived solely from a device manual. Real quotes can still be semantically irrelevant: the deterministic audit and semantic review must both pass.

Use at most one repair attempt per section, provided valid passages exist. Audit repaired claims again. If unresolved, publish an explicit `needs_review` section with reasons and preserve the rejected draft for internal audit. Model/timeouts/invalid JSON do not become `supported` outcomes. This separate reviewer call is procedurally independent; the same model may repeat correlated mistakes, so do not call it a guarantee.

Migrate existing `run_ask` auditing to shared helpers while preserving its conservative abstention behavior. Bind reviewer results to the claim revision and source-context hash so they cannot be reused after edits.

Tests: absent claim audit, fabricated quote, valid but irrelevant quote, negation reversal, contradictory passages, wrong corpus role, missing legal qualifier, unsupported applicability and prompt injection. Include a case in which a quote is genuine but the status overstates coverage. Use deterministic fixtures/mocked model outputs; real semantic performance needs human labels.

## Stage 7 — Wire the six roles, CLI and report updates

### Codex prompt

```text
Implement Stage 7. Wire the six typed roles into the orchestrator, using
all preceding shared components. Keep pipeline.py as the compatibility
facade. Add resume and targeted-requirement CLI operations. Extend the
deterministic report writer and provenance graph to display new evidence
statuses and audit outcomes. Add an API-free end-to-end workflow test.
```

Role boundaries:

| Role | Allowed responsibility | Output |
|---|---|---|
| Requirement Analyst | Extract explicit atomic obligations from selected legal text and verify anchors | Versioned register |
| Applicability Analyst | Assess scope using cited legal conditions and explicitly unverified profile facts | Applicability result and missing facts |
| Evidence Retriever | Plan queries, retrieve, fuse, rerank and gate | RetrievalResult + SourceBuffer references |
| Evidence Reviewer | Draft and independently check evidence claims | Reviewed finding and structured audit |
| Citation Auditor | Validate identities, hashes, raw quotes and locations | Audit result |
| Report Writer | Render validated state and derived summaries | JSON/Markdown exports |

Unknown applicability does not automatically skip retrieval. `possibly_not_applicable` remains tentative. In the first implementation, default to searching device evidence even for that result; any future skip policy must be explicit, sourced and visible.

CLI target after Stage 7 (basic assessment IDs, resume, targeted refresh and report rendering were added in Stage 1; cross-encoder options and six-role orchestration remain pending):

```powershell
python main.py --retrieval hybrid --reranker cross_encoder review --limit 2 --assessment-id demo01
python main.py review --assessment-id demo01 --resume
python main.py review --assessment-id demo01 --requirement-id R-EXISTING-ID --refresh
python main.py report --assessment-id demo01
```

Replace `R-EXISTING-ID` with an actual register ID. Resolve configuration through saved state when resuming; a changed CLI override invalidates affected stages rather than silently mixing configurations. Validate `--limit > 0`, positive `--k`, known IDs and incompatible options. Explicit refresh creates a new section revision; resume only continues unfinished/stale work. Summaries derive from the full state, not just the latest invocation's subset.

Reports show legal source/version/scope, applicability separately from evidence status, missing facts, every published claim's quoted sources, review/audit results, stale/failed/pending sections and whether gating was calibrated. Keep existing compatibility fields for graph/report consumers. New graph edges may distinguish retrieved, cited, contradiction and audited-support links; a cited edge is not compliance proof.

Report Writer adds no novel findings. Render unreviewed legacy findings with their original limitations. Never silently promote them. Streamlit assessment controls are an optional later stage; complete and verify the CLI first.

Tests: complete six-role synthetic run, gate short-circuit, invalid schema, interrupted resume, targeted R2 edit without R1/R3 LLM calls, reviewer repair budget, legacy graph/export compatibility and truthful partial-run counts. No live Ollama or model download in the default test suite.

## Stage 8 — Evaluate the full upgrade and document operation

### Codex prompt

```text
Implement Stage 8. Make evaluation use the production candidate/reranking
pipeline, add comparison experiments and held-out abstention/grounding
evaluation, and document reproducible operation on CPU. Keep synthetic
fixtures clearly separate from human-validated gold. Produce an honest
evaluation report with latency, failures and dataset limitations.
```

Compare: dense; BM25; hybrid; multi-query hybrid; multi-query plus cross-encoder; complete pipeline including gate and reviewer. Preserve candidate budgets in the comparison or report differences explicitly. Do not benchmark the new backend under the old generic `hybrid_reranked` label without backend identity.

Inspect `evaluation.load_gold`: the existing format requires nonempty relevant labels. Extend it explicitly to support unanswerable cases with a label such as `answerable=false`, without conflating malformed positive labels with valid negative cases. Handle retrieval metrics with no positives separately to avoid undefined recall denominators.

Track Recall@k, nDCG@k and MRR; candidate recall before reranking; passage relevance precision; answerable-case retention; abstention on unanswerable cases; human-adjudicated claim support and contradiction misses; citation-ID/span validity; reviewer coverage; median/p95 stage latency; failure counts; peak memory where measurable.

Start labeling 20–50 diverse queries/requirements if feasible, but report the actual sample size and split counts. Small splits are exploratory, not a reliable calibration guarantee. Use negative and ambiguous examples, qualification/exception cases, cross-document evidence, historical/version differences and prompt-injection fixtures. Never derive gold labels directly from the model under evaluation.

Record legal/device document hashes, source-version labels, model revisions, prompts, score transformations, context/token limits and all retrieval parameters. Keep sensitive excerpts out of public evaluation artifacts unless authorized.

Proposed end-user verification after implementation:

```powershell
python -m pytest -q
python main.py --help
python main.py inspect
python main.py --retrieval hybrid explore "risk management records" --kind device --k 10
python main.py --retrieval hybrid --reranker cross_encoder review --limit 2 --assessment-id first_test
python main.py review --assessment-id first_test --resume
python main.py report --assessment-id first_test
```

The new review commands need an existing requirement register, a matching index, local models and the configured calibration policy. Do not use sample page numbers as real MDR anchors. Baseline and held-out retrieval evaluations need actual human-verified gold data.

## Suggested initial configuration additions

These are proposed settings to implement and validate, not currently supported environment variables:

```dotenv
MULTI_QUERY_ENABLED=true
MULTI_QUERY_MAX=4
RETRIEVAL_PER_QUERY=12
RERANK_BACKEND=cross_encoder
RERANK_MODEL=BAAI/bge-reranker-base
RERANK_DEVICE=cpu
RERANK_BATCH_SIZE=4
RERANK_MAX_CANDIDATES=30
EVIDENCE_GATE_MODE=strict
EVIDENCE_GATE_CALIBRATION=eval/calibration/evidence_gate.json
REVIEW_MAX_REPAIRS=1
```

Do not add a fake calibration file just to make strict mode run. The calibration path should be absent until a labeled calibration experiment creates it; strict mode then abstains with an explicit reason. Test none/LLM backends independently and document their gate policies. Candidate/context limits are starting budgets, not measured optimal values.

## Completion checklist

- [x] Stage 0: local baseline and configuration corrected.
- [x] Stage 1: resumable ReportState and targeted revisions.
- [ ] Stage 2: immutable SourceBuffer with raw span links.
- [ ] Stage 3: bounded multi-query retrieval and production trace.
- [ ] Stage 4: optional scored CPU cross-encoder.
- [ ] Stage 5: calibrated gate and truthful abstention.
- [ ] Stage 6: claim-complete grounded review and deterministic citation audit.
- [ ] Stage 7: six-role orchestration, CLI and compatible reports.
- [ ] Stage 8: production-aligned evaluation and operating guide.

### Stage 0 completion record

- Stage 0 verified on 2026-10-13 against checkout `89d8c02047743b35354c4006c5c5fa9c96b0b5b1` plus working-tree changes; implementation commit recorded in Git history on `qmatrix-impelmantion`.
- See [stage0_baseline.md](stage0_baseline.md) for reproducible commands, pre-existing environment errors, 25 passing pre-change tests and 31 passing post-change tests, preservation details and live baseline blockers.
- Only mocked/API-free review/retrieval verification was possible: the requested chat model is not installed and the real gold set is empty. No index rebuild or assessment overwrite occurred.

### Stage 1 completion record

- Implemented typed schema-v1 state, assessment locks and expected revisions, atomic checkpoints/revision history, dependency invalidation, resume and targeted refresh, compatibility exports and explicit non-destructive legacy import.
- New requirement IDs use deterministic legal anchors; matching existing IDs are retained and paraphrase revisions recorded. Independent reviewer/citation audits remain later-stage work.
- Verification: 31 pre-change tests and 70 post-change tests passed; CLI help and `git diff --check` passed. See [stage1_verification.md](stage1_verification.md) for commands, preservation and limitations.
- Implementation commit is recorded in Git history on `qmatrix-impelmantion` as "Add resumable assessment state and targeted review updates".

For each completed stage, record the implementation commit, checks run, observed results and remaining limitations. A mocked test passing establishes code behavior; it does not establish regulatory reasoning accuracy.

## Technical references

- Inspected repository: https://github.com/isidorapopovic/medical-device-rag/tree/e56ce7814f27caedf7d9bda3adbaca22fe04f066
- BGE reranker model card and usage: https://huggingface.co/BAAI/bge-reranker-base
- Sentence Transformers CrossEncoder API: https://www.sbert.net/docs/package_reference/cross_encoder/model.html

The BGE documentation supports reranking query/passage pairs after initial retrieval. The state model, role contracts, gate policy, revision rules and staged migration here are proposed designs for this repository. No external Q-Mix implementation or claimed benchmark result was assumed.
