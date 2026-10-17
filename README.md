# Medical Device RAG

The supported application uses **Ollama locally** for embeddings and structured language-model tasks. The supported entry points are `main.py` (CLI) and `streamlit_app.py` (document upload, indexing, preview and single-turn Q&A); shared application code is in `mdr_rag/`. These workflows do not require OpenAI or Gemini API keys.

`rag.py` is a separate, older Gemini prototype retained for reference, not the supported application. It imports `mdr_rag.tls` and `mdr_rag.quota`, which are not present in this checkout, and expects Gemini dependencies and credentials not used by the modular app. Do not use it for the supported workflow; use `main.py` instead. The script is retained in place. It uses the same `vector_db/` directory but a separate collection named `medical_device_rag_<Gemini embedding model with hyphens replaced by underscores>`; the modular app uses `medical_mdr_evidence`. Do not delete, migrate or reuse the legacy collection as an Ollama index.

## Quick start

### Windows (PowerShell)

Install and start Ollama, then run:

```powershell
ollama pull embeddinggemma
ollama pull qwen3:4b
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python main.py inspect
python main.py index
python main.py ask "What does the MDR say about risk management?"
```

### macOS / Linux

Install and start Ollama, then run:

```bash
ollama pull embeddinggemma
ollama pull qwen3:4b
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python main.py inspect
python main.py index
python main.py ask "What does the MDR say about risk management?"
```

The default embedding and language models are `embeddinggemma` and `qwen3:4b`. Change `EMBEDDING_MODEL` or `OLLAMA_LLM_MODEL` in `.env` to use different Ollama models. Retrieval defaults to hybrid dense + BM25; use `RETRIEVAL_MODE=dense` or `RETRIEVAL_MODE=bm25` to change it. BM25-only retrieval does not call the embedding model. The `--retrieval` and `--rerank` options are global CLI options and go before the command, for example:

```powershell
python main.py --retrieval bm25 ask "What does the MDR say about risk management?"
python main.py --rerank ask "What does the MDR say about risk management?"
```

`--rerank` uses the local Ollama language model on a small candidate set and may be slower, especially on CPU. Dense and hybrid retrieval need Ollama embeddings and an indexed Chroma database. Ollama must be running at its normal local address.

Before indexing, copy original MDR PDF into `documents/legal/` and medical device files into `documents/device/`. Then use `locate`, `extract`, `review`, `visualize-embeddings`, `evaluate`, and `graph` as documented below.

On CPU, indexing and structured legal extraction may be slow. The legal requirements and regulatory reports remain **draft evidence mappings**, not legal approvals. Small local models can omit obligations and return invalid structured outputs; review their results carefully.

Changing `EMBEDDING_MODEL` requires an intentional index rebuild before using that model with existing data. `index` prepares a complete replacement of the modular collection and retains the old collection as a recovery backup; do not run it just to verify an existing baseline. Model execution is local, but review your own confidentiality/security requirements.

## Local configuration and baseline checks

`.env.example` lists the local settings read by the modular app, including: `EMBEDDING_MODEL=embeddinggemma`, `OLLAMA_LLM_MODEL=qwen3:4b`, `OLLAMA_NUM_CTX=8192`, `RETRIEVAL_MODE=hybrid`, `RERANK_ENABLED=false`, and `LEGAL_VERSION=UNSPECIFIED HISTORICAL TEXT`. These are app defaults, not performance guarantees. `LEGAL_VERSION` is a user-supplied label, not a verified legal edition. `OLLAMA_NUM_CTX` must be a positive integer supported by your local model. Retrieval accepts `dense`, `bm25`, or `hybrid`; reranking accepts `true` or `false`. CLI overrides take precedence; otherwise process environment variables take precedence over `.env`, then code defaults apply. The setup commands above preserve an existing `.env`.

After activating the project virtual environment, `python main.py --help` needs installed Python dependencies but no Gemini credentials or inference. Run `python -m pytest -q` for API-free tests. If Windows temp-folder permissions block pytest, use a fresh writable directory, for example `python -m pytest -q --basetemp reports/test-temp-stage0`. Pytest clears the chosen directory, so always choose a dedicated test-only path.

Reviews now have persistent assessment IDs. Use `python main.py review --assessment-id baseline01 --limit 2` for a distinct review; evaluation supports `python main.py evaluate --gold eval/gold_queries.json --out reports/baseline01/retrieval_evaluation.json`. Reviews require matching existing state/index and installed local models; evaluation also requires real human-verified gold labels. Do not use illustrative labels as measurements. The dated [Stage 0 baseline](docs/stage0_baseline.md) records the original availability blockers; [Stage 1 verification](docs/stage1_verification.md) records persistence tests; [Stage 2 verification](docs/stage2_verification.md) records raw-span provenance tests; [Stage 3 verification](docs/stage3_verification.md) records bounded query planning and retrieval tests; [Stage 4 verification](docs/stage4_verification.md) records backend and CPU model checks; [Stage 5 verification](docs/stage5_verification.md) records the evidence gate and calibration workflow; [Stage 6 verification](docs/stage6_verification.md) records claim auditing, semantic policy and bounded repair tests; [Stage 7 verification](docs/stage7_verification.md) records the six-role CLI workflow and saved configuration checks; [Stage 8 verification](docs/stage8_verification.md) records production-path evaluation tests, and [the evaluation report](docs/stage8_evaluation_report.md) records the actual dataset and runtime limitations.

## Stage 01 runtime foundations

Supported Ollama calls now share a run-scoped usage ledger at `state/runtime.sqlite3` and redacted JSON events at `state/runtime.jsonl`. Existing assessment JSON, immutable source snapshots, CLI flags and report formats remain authoritative and are not copied into SQLite. The database initializes lazily on the first model operation; help and file inspection do not initialize clients or the ledger. SQLite migrations are transactional, versioned and reject newer unknown schemas.

The defaults are 30 total model-operation attempts (including embeddings, optional reranking and retries), 120,000 input tokens, 16,000 output tokens, 16,000 prompt characters per call, 1,200 generated tokens per call, 1,200 seconds per invocation and 120 seconds per transport request. Every attempt reserves usage before inference. Reported counters replace reservations after a successful response; absent counters retain conservative estimates. Ollama input estimates use serialized UTF-8 bytes plus framing allowance, rather than pretending characters divided by four are measured tokens. CPU scorer inputs use actual prepared pair-token counts. Embedding batches split without truncating their source text. Limits may stop large indexing/review jobs sooner than before; change the explicit settings deliberately for a larger local run.

Only transient timeouts/network transport failures and selected busy/server responses are retried, at most twice after the first attempt, with bounded backoff and jitter. Missing models, refused connections, invalid inputs, authorization errors and invalid structured outputs are not retried. Final failures close the run; no local-to-cloud fallback occurs. Cancellation is cooperative between synchronous calls; an in-flight HTTP operation uses SDK transport timeouts, while native CPU inference is checked before/after scoring and cannot be forcibly interrupted. Transport timeouts apply to HTTP phases, not a guaranteed hard process-kill deadline. The wall-time check discards late results.

`mdr_rag.settings.load_settings()` reads defaults, `.env`, then process environment without mutating it. `Settings.safe_dump()` excludes credentials, file paths, model identifiers and edition labels. Ollama endpoints must be loopback HTTP; environment proxies and redirects are disabled in the adapter. Cloud is off by default, and there is no cloud provider implementation even with explicit configuration opt-in. New provenance contracts live in `mdr_rag/contracts.py`; legacy finding/profile adapters preserve old output vocabularies and do not promote unverified facts. `mdr_rag.providers` supplies injectable interfaces and deterministic synthetic fakes.

Settings and rollout details are in `.env.example` and the local `docs/implementation/` notes. Existing `.env` is preserved. An invocation gets a new UUID and budget, including a resumed legacy review; pending reservations from a crash remain charged to their original run. This is an invocation budget, not a lifetime project quota or cross-invocation circuit breaker. No historical finding is erased by ledger initialization.

Offline smoke checks (activate `.venv` first):

```powershell
python main.py --help
python -m pytest -q tests/test_foundations.py --basetemp reports/test-temp-foundations-smoke
```

Expected: CLI help and deterministic foundations tests pass without Ollama, network, cloud credentials or model weights. Use a dedicated new test temporary path; pytest owns that directory. See the Stage 01 progress document for exact measured results and integration checks not run.

## Stage 02 ingestion and original-file provenance

PDF/DOCX/TXT/Markdown ingestion archives originals and immutable extraction manifests under `state/ingestion/<project hash>/`. Files retain their byte SHA-256, document UUID, revision, MIME and extraction/library versions. Identical re-uploads reuse the same revision; changed bytes under the same logical name create a new revision. Each project and legal/device collection has its own logical document identity. Uploaded filenames never select archive paths. Symlink/junction paths, reserved Windows names, MIME mismatches, unsafe DOCX archives and oversized inputs are checked before publication.

Streamlit uploads now archive revisions before updating the latest working file in `documents/legal` or `documents/device`. Original revisions remain in the archive. The legacy low-level `save_uploaded_document` helper still refuses overwrites and intentionally does not parse content; supported UI uploads use the validated ingestion service. The UI provides local upload, indexing, preview and single-turn Q&A; assessment controls remain in the CLI.

Extraction preserves PDF physical pages, DOCX paragraph/table/row/cell order, and TXT/MD block/line locations. Text is normalized once using a named NFC/whitespace policy with a character-to-raw-extraction offset map. Source views show the normalized quote, its raw excerpt and surrounding context, and the original revision's path/page. Offsets refer to Python characters in extracted text, not PDF binary bytes or printed page labels. DOCX/text locations are never called physical pages. Headings are literal structural labels, not inferred regulatory requirements.

Native PDF table reading order is not structurally verified; warnings identify that limitation. DOCX headers, footers, drawings and nested table omissions are diagnosed. Scanned/blank pages become `needs_ocr` or make an otherwise readable document `partial`; failed pages produce no source spans. Encrypted/damaged files, unexpected encodings and empty extraction are explicit diagnostics. Unreadable legal files block indexing rather than silently yielding device-only evidence.

```powershell
python main.py ingest --file documents/device/synthetic_notes.md --kind device --project-id local
# Copy manifest_sha256 and a source_span_id from the returned JSON:
python main.py source-view --manifest MANIFEST_SHA256 --span SOURCE_SPAN_ID --project-id local
python main.py index
# Deliberately recompute all vectors, e.g. after changing weights behind a mutable model tag:
python main.py index --force-reembed
```

`ingest` archives/parses without indexing or model calls; `source-view` prints private source excerpts only when explicitly requested. The legacy CLI/index uses the `local` project. Other project IDs are supported by the archive/service but are not merged into the legacy vector collection. Repeated indexing reuses matching vectors only when model and project metadata agree. All required embeddings and the candidate collection finish before promotion. Previous collections are retained as named backups; automatic backup deletion is deliberately absent. Collection rename/promotion and the subsequent atomic manifest write are separate local operations, not one database transaction; if manifest publication fails, stop and investigate the retained backup before further review.

New source snapshots use schema 2 with a bound archive reference. Existing schema-1 snapshots/IDs remain readable and unchanged; historical citations with no original archive are explicitly identified as legacy rather than assigned invented revision provenance. New index manifests verify archived originals when reused for review. Nothing in this upgrade automatically re-indexes or rewrites existing data.

Limits: 50 MiB input, 100 MiB expanded DOCX with compression/member/XML checks, 2,000 PDF pages, 20,000 extraction units, 5,000,000 extracted characters, bounded Unicode clusters and context excerpts. Native parser calls are synchronous; these resource limits are not a hardened parser sandbox. OCR is disabled by default. `OCR_ENABLED=true` plus explicit `ingest --ocr` opts into installed local PyMuPDF/Tesseract support, at most 20 scanned pages and bounded raster size; no engine/language data is downloaded. Missing OCR is diagnosed, and OCR-derived text remains visibly unverified. OCR uses shared run-call/deadline guards; its character/image work is not reported as measured LLM tokens. Archived OCR extractions are inspectable but are not silently substituted for native legal evidence in the legacy index.

Deterministic smoke: `python -m pytest -q tests/test_ingestion.py -p no:cacheprovider --basetemp reports/test-temp-ingestion-smoke`. Fixtures are synthetic; no real dossiers, official provisions, ground truth, downloads or model calls are used. Archive snapshots and `source-view` output are private; do not publish them.

## Bounded review query planning

Reviews default to `MULTI_QUERY_ENABLED=true`: the original obligation query plus up to three artifact, process/test and requirement/profile qualifier intents. Expansions use obligation text and explicitly supplied device name/intended purpose; they do not infer legal obligations or classification. `QUERY_PLANNER=deterministic` is the default. Optional `QUERY_PLANNER=llm` lets the local model select from this sourced menu; malformed JSON or unknown selections use deterministic templates and save a fallback reason. The original query is always retained. `ask` remains a single-query command.

`MULTI_QUERY_MAX=4`, `RETRIEVAL_PER_QUERY=12`, and `RETRIEVAL_MAX_CANDIDATES=30` are hard upper bounds (each may be reduced). Each query retrieves at most 12 candidates per selected backend. Reciprocal-rank fusion first combines dense/BM25 lists within each query, then combines query lists. Duplicate query texts and chunk IDs receive no extra votes within a list; ties use chunk ID. Raw vector distances and BM25 scores are never summed. The merged pool is capped at 30 before optional reranking against the original query plus explicitly supplied essential profile qualifiers; `--k` selects final passages and accepts 1..30. Tokenization/BM25 construction is cached in memory by database, corpus kind and manifest fingerprint for reviews, with four cached corpora at most.

Canonical sections and finding history save `query_plan` and `retrieval_trace`: per-query candidate lists, query/backend ranks, fused pool and selected IDs. Retrieved candidates are separately snapshotted, model calls record actual presented ranges, and findings keep validated cited spans. Retrieval provenance is not evidence that a model saw or cited every candidate. Older schema-2 reports load with these optional fields absent; changed query/retrieval versions invalidate reuse without rewriting historical snapshots. Planning settings invalidate query construction onward; candidate budgets invalidate retrieval onward. With LLM planning, model/context changes also invalidate planning. `MULTI_QUERY_ENABLED=false` retains single-query retrieval. Reranked reviews still record candidate and score diagnostics; the unreranked compatibility path omits that trace.

Stage 8 evaluation now calls the production candidate API, including the same fusion, corpus filters, cache and optional reranking. Explicit multi-query comparisons use the production planner; deterministic fixtures remain behavior checks, not project performance measurements.

## Optional reranker backends (Stage 4)

Reranking remains off by default. `--rerank` preserves the Ollama LLM behavior and forces `llm`, even if the environment names another backend. Select explicitly with `--rerank-backend none`, `llm` or `cross_encoder` before the command; the two CLI options are mutually exclusive. A nonblank `RERANK_BACKEND` overrides `RERANK_ENABLED`; leaving it blank preserves the legacy true/false setting. Ollama still provides generation and embeddings. The cross-encoder is separate local inference, and errors never substitute another backend.

```powershell
python main.py --rerank-backend llm review --assessment-id llm-review --limit 2
python main.py --rerank-backend cross_encoder review --assessment-id ce-review --limit 2
python main.py --rerank-backend none ask "Synthetic question"
```

The minimal `requirements.txt` has no cross-encoder packages. To opt in, install the separately pinned stack and explicitly provision public model files (these two operations need internet; inference does not):

```powershell
python -m pip install -r requirements-rerank.txt
python -m mdr_rag.download_reranker
```

The initial model is `BAAI/bge-reranker-base`, pinned to commit `2cfc18c9415c912f9d8155881c133215df768a70`. It is an engineering benchmark choice, not the default. `CROSS_ENCODER_CACHE` defaults to ignored `reports/reranker-cache`; the provisioning helper uses ordinary local files to support Windows without symlink privileges. Inference requires a complete pinned snapshot already on disk and uses no download or cloud call. `CROSS_ENCODER_MODEL` accepts namespace/model IDs; another model requires an explicit 40-character revision and a compatible single-logit, fast-tokenizer architecture. Installed Sentence Transformers/Transformers/PyTorch/tokenizers/safetensors versions, weight/tokenizer/config hashes, revision, preprocessing implementation and score transformation are fingerprinted and saved. Backend/model/library/preprocessing changes invalidate retrieval and downstream review stages. The model loads lazily once per fingerprint per process; help and the `none`/`llm` paths never load it.

At most 30 original-query/candidate pairs are scored once, with `CROSS_ENCODER_BATCH_SIZE=4` (allowed 1..4), explicit CPU float32, four CPU threads and eager attention. `CROSS_ENCODER_MAX_TOKENS=512` (allowed 32..512) counts the combined pair including special tokens, not characters. Preprocessing retains a query prefix of at most 128 tokens, then right-truncates only the passage to fit the remaining pair budget. Long queries, including appended unverified profile qualifiers, can themselves truncate; query character bounds and flags are logged. Fast tokenizer offsets retain original parent-chunk character bounds, exact encoded-input hashes, token counts and passage truncation flags. The pretokenized tensors are fed to the model loaded by `CrossEncoder`, avoiding a second untracked truncation inside `predict()`.

Scores are raw single-output logits (identity transformation), with stable ties following the original fused candidate order. Scored outputs contain sorted copies; IDs, text, hashes and query/backend provenance remain intact. Canonical retrieval/model-call traces and compatibility JSON retain every candidate score and its token range. `rerank_citation_coverage` records whether each verified quote lies within the cross-encoder's token-offset envelope; quotes outside it are not marked scored. This is a conservative character envelope of tokens, not a promise that every source character survives tokenizer normalization. LLM score traces identify submitted text but explicitly leave actual token visibility unverified. Historical reports retain their original score/context limitations.

Cross-encoder relevance scores are not evidence sufficiency, compliance probabilities or calibrated legal confidence. Applying a sigmoid would not change that. The initial CPU latency/memory observations and opt-in smoke command are in [Stage 4 verification](docs/stage4_verification.md); benchmark on your own corpus before selecting a default. Evaluation records backend-specific method names, identities and scored/truncated input ranges; it no longer benchmarks a cross-encoder under the generic `hybrid_reranked` label.

## Evidence gate and calibration (Stage 5)

Reviews default to `EVIDENCE_GATE_MODE=strict`. The gate runs after reranking and before drafting, screens the full merged pool (at most 30), then chooses up to `--k` accepted passages. With no matching calibration, it saves `insufficient_evidence` with `threshold_not_calibrated` or `calibration_mismatch` and calls no drafting model. This describes a screening limitation, not absent documentation or non-compliance. Missing indexes, empty indexed corpora, invalid scores and backend failures are execution errors. An empty retrieval response from a nonempty corpus is separately recorded as abstention. Rejected passages never re-enter through a top-k fallback.

Strict mode reads `EVIDENCE_GATE_CALIBRATION` when supplied. It binds the threshold to exact scorer/model/revision, transformation, library/artifact identity, query/planner/retrieval configuration, corpus and profile fingerprints. RRF scores are never thresholded. No distance-based gate is implemented, no `1 - distance` conversion occurs, and the existing collection's unconfigured metric is not assumed to be cosine. The scored source is explicitly `reranker`; Chroma distances remain retrieval inputs only. Current cross-encoder snapshots support strict calibration. Mutable Ollama tags lack a pinned weight digest, so current LLM scores can be used experimentally but cannot produce a strict calibration artifact.

`EVIDENCE_GATE_MODE=experimental` requires a user-selected finite `EVIDENCE_GATE_THRESHOLD`; no numeric default is supplied and the report labels it uncalibrated. It requires a working reranker with a complete score map. `EVIDENCE_GATE_MODE=disabled` deliberately bypasses relevance screening and is visible in JSON and Markdown; it never counts as successful strict validation. `ask` retains its existing answer-support workflow; this Stage 5 gate applies to `review`.

To obtain a real calibration, collect a **new** scored review with a pinned local cross-encoder and existing valid index/register. Strict mode without a calibration is useful for collecting scored candidate snapshots without drafting. Do not rebuild an index merely for calibration:

```powershell
python main.py --rerank-backend cross_encoder review --assessment-id gate-scored-run
```

Copy [the label template](eval/evidence_gate_labels.EXAMPLE.json) to a new local file. Independently review source snapshots and actual reranker token ranges in canonical state. Set answerable/unanswerable truth from the corpus, annotate **every scored candidate** using `relevant` booleans and `positive`, `negative` or `hard_negative`, and record the reviewer. Use distinct questions in `calibration` and `held_out`, with both answerable/unanswerable cases and positives/hard negatives in each split. Avoid paraphrase/family leakage through human review too; exact duplicate query fingerprints are rejected automatically. Use archived state revisions as label sources so later updates cannot change the measured scores. Paths in the label file resolve relative to that file. The example's truth labels are placeholders and `human_validated=false` prevents its use. Do not hand-enter scores; the tool reads them from completed, bound reranker calls and verifies their source snapshots.

```powershell
python main.py calibrate-gate --labels eval/reviewed_gate_labels.json --out state/calibrations/gate-v1.json
python main.py evaluate --gate-labels eval/reviewed_gate_labels.json --gate-calibration state/calibrations/gate-v1.json --out reports/gate-v1/heldout.json
```

Tuning maximizes calibration-set balanced question accuracy (positive-passage hit rate and unanswerable abstention), then passage F1, then the higher threshold for ties. Candidate cutoffs come only from calibration scores, with an additional all-reject boundary. Held-out cases do not influence selection. The artifact contains model/revision/transformation, retrieval/corpus/profile context, label fingerprint, threshold, calibration/held-out metrics and UTC date. It uses an exclusive lock and atomic same-directory replacement into a **new filename**; existing calibration artifacts are never overwritten. Evaluation freezes that threshold, excludes calibration cases/questions, and reports passage confusion counts, precision/recall/F1, answerable hit rate, unanswerable abstention and false-accept rates. It performs no new inference. These are relevance/abstention metrics, not answer faithfulness, sufficiency or legal confidence. No real threshold was calibrated during Stage 5 verification because independently reviewed project labels were not supplied.

After reviewing the held-out results, set `EVIDENCE_GATE_CALIBRATION` to that artifact in your own environment and resume/update a review. Calibration or threshold changes invalidate the gate and downstream stages, preserving retrieval; switching between disabled and enabled gating invalidates retrieval because the candidate pool changes from final k to the full merged pool. Profile, corpus or scorer changes invalidate retrieval and also fail old calibration matching. Decisions, accepted/rejected IDs, every available score/reason, calibration fingerprint and draft IDs survive the gate checkpoint, finding history and compatibility exports. `audit_status=gate_abstained` means no draft/raw-claim audit was performed.

Relevance is followed by an atomic-obligation coverage inventory. Existing atomic registers use their requirement ID/text; optional explicitly registered `atomic_obligations` and `qualifiers` are retained without inventing a decomposition. The drafting model reports coverage for each obligation using only accepted, presented evidence. Missing/unknown coverage or rejected IDs result in `needs_review`; partial obligations may retain `partial`, while an asserted complete finding with unaddressed explicit qualifiers fails validation. Raw cited spans still require Stage 2 validation. Stage 6 separately reviews claim support and obligation coverage as described below; specialist review remains necessary.

## Structured claims and separate review (Stage 6)

`review` drafts `StructuredFinding`: status, inventoried claims and atomic-obligation coverage. Each claim has an ID, text, category, obligation IDs, legal/device role and exact citations. Assessment text, factual reasons, missing-information assertions, proposed actions and applicability assertions all come from this inventory; free narrative outside it is rejected. A pure recommendation may omit citations only when the reviewer finds that it implies no unverified facts.

A separate local model call receives the atomic requirement, explicit applicability uncertainty, complete draft inventory and only the selected legal/device snapshot ranges. It must return exactly one `supported`, `contradicted` or `insufficient` verdict for every draft claim ID and coverage for every atomic obligation. It checks negation, modality, exceptions, device scope, contradictory passages and completeness of legal qualifiers. Draft and reviewer citations both pass the deterministic `CitationAuditor`: immutable identities, corpus roles, file/text hashes, raw offsets, locators and allowed context membership. Device facts require device evidence; legal duties require legal evidence; mixed/applicability claims require both. An unverified device profile cannot establish applicability. A genuine quotation alone cannot make a finding pass.

Passing requires both citation and semantic validation, including consistency between claimed complete coverage, explicit qualifiers and cited claim/obligation IDs. At most **one repair attempt per section draft cycle** uses the same valid source context. The budget is saved before inference; an interrupted repair cannot grant another attempt. Repaired claims receive a new completed generation binding and are audited again. If unresolved, publication contains an explicit `needs_review` section and machine-readable reasons, with no rejected factual narrative or citations. Rejected drafts and complete reviewer outputs remain internal in canonical state/history, while compatibility exports expose only validation metadata. Initial draft/model/JSON failures remain explicit failed executions; reviewer/repair failures cannot produce a supported finding. A section with no retained evidence still bypasses generation and semantic calls.

The `validation` checkpoint resumes without repeating completed extraction, retrieval or drafting. Reviewer reuse requires an exact claim-revision and source-context hash, including the generation call and reviewer configuration. Semantic publication bindings are checked when state is loaded. `audit_status=semantic_checked` records passing procedural checks; `validation_failed` records an unresolved review. Older raw-only audits keep their original status. `ask` uses the shared auditor and policy, renders only inventoried claims and conservatively abstains on omitted/duplicate/invented claim IDs, invalid quotes, rejected semantics or reviewer failures; it has no repair loop.

Inputs and source passages are untrusted data, never executable instructions. The same local model can draft and review, so errors may be correlated. These checks are **not a guarantee of entailment, legal completeness, safety or compliance**. Deterministic mocked tests establish workflow behavior; real semantic performance needs independently human-labeled claims and coverage cases. No new model installation, cloud service or configuration setting is required.

## Six-role CLI orchestration (Stage 7)

`pipeline.py` remains the compatibility facade. `AssessmentOrchestrator` dispatches checkpoint work through typed local roles; these roles reuse the existing query planner, shared retrieval/fusion API, rerankers, relevance gate, SourceBuffer and claim-review policy.

| Role | Responsibility and typed output |
|---|---|
| Requirement Analyst | Explicit atomic legal extraction and verified anchors; `VersionedRegister` with stable IDs, requirement revisions, a register fingerprint and archived register snapshots. Resume consumes this register and never extracts again. |
| Applicability Analyst | `ApplicabilityResult` with cited legal conditions, explicitly unverified profile facts and missing facts. The initial deterministic method checks only an actor condition literally present in a verified anchor; a scope paraphrase alone cannot establish it. |
| Evidence Retriever | Query planning, candidate retrieval/fusion, reranking and gate checkpoints; `RetrievalResult` retains candidates, query/backend provenance, gate decisions and immutable buffer references. |
| Evidence Reviewer | Structured drafting, separate semantic review and bounded repair; `ReviewedFinding` retains the finding, review records and audit outcome. |
| Citation Auditor | Deterministic identity/hash/role/span/context checks; `AuditResult` distinguishes performed/passed checks from work not performed. |
| Report Writer | Deterministic JSON/Markdown export and full-state summaries; `ReportExport` adds no novel findings. |

Profile facts are never marked verified. A cited actor condition that differs from the unverified `actor_role` may produce **tentative** `possibly_not_applicable`; otherwise the initial analyst remains `uncertain` and requests specialist verification. It does not infer device classification, exceptions, current law or confirmed applicability. Both outcomes use the visible `search_device_evidence` policy. Applicability and evidence status are separate: a passage may address an obligation even when device scope remains uncertain.

```powershell
python main.py --retrieval hybrid --reranker cross_encoder review --limit 2 --assessment-id demo01
python main.py review --assessment-id demo01 --resume
python main.py review --assessment-id demo01 --requirement-id R-EXISTING-ID --refresh
python main.py report --assessment-id demo01
# Explicitly adopt edited environment settings, including a new calibration artifact:
python main.py review --assessment-id demo01 --resume --use-env-config
```

Use an actual register ID. `--reranker` aliases `--rerank-backend`; legacy `--rerank` still selects the LLM backend. The cross-encoder must be provisioned locally as described above. Strict gating still requires matching human-reviewed calibration; selecting a reranker alone does not calibrate it. `--limit` and `--k` must be positive, and unknown IDs or incompatible resume/refresh/limit options fail explicitly. Refresh creates a new section revision; resume continues unfinished/stale work only. A changed CLI override marks all affected sections stale but performs expensive work only for selected sections. Summaries always cover the full assessment.

New extraction archives both the previous register bytes and the new typed register beneath `state/requirements/revisions/`, guarded by an exclusive register lock and an optimistic content check. It writes through same-directory temporary files and atomic replacement. Concurrent extraction cannot silently overwrite a changed register. A deliberate manual register edit must preserve IDs/revise requirements and update its fingerprint (or leave `register_fingerprint` blank for validation to derive it); original assessment/register snapshots remain available.

Markdown shows applicability/missing facts separately, every published claim and verified quoted sources, gate calibration and review/audit outcomes. Graphs retain compatibility citation counts and add distinct retrieved, raw-cited, contradiction, legal-scope and reported model-audited support relations. Pending, failed and stale requirements appear separately from assessed findings; unassessed sections are not counted as missing documentation. A cited or model-audited edge is not proof of compliance. Unreviewed legacy findings retain their original limitations and are never silently promoted. Streamlit assessment controls remain outside this CLI stage.

## Persistent reviews, resume and updates

The existing requirement register is reused; resume never runs extraction. Start a named assessment, continue it, or refresh one actual requirement ID from the register:

```powershell
python main.py review --assessment-id study01 --limit 2
python main.py review --assessment-id study01 --resume
python main.py review --assessment-id study01 --requirement-id R-ACTUAL-ID --refresh
python main.py report --assessment-id study01
```

A review without `--assessment-id` generates a new ID and prints it. Reusing an existing ID requires `--resume` or `--requirement-id`. `--resume` continues pending/failed/stale sections; `--requirement-id` processes only the named section if unfinished or stale, and `--refresh` deliberately starts a new finding revision for that section. It cannot be combined with `--resume`. `--limit` must be positive and cannot be combined with a requirement ID; on resume it selects the first N entries of the full register, skipping already completed entries. An omitted `--k` reuses the saved value (new assessments default to 7). Continuation and current report rendering resolve settings from saved state. Explicit CLI overrides invalidate affected stages; `--use-env-config` explicitly adopts current environment settings. Inference runs under the resolved settings, restored after the operation. Source/profile changes and implementation/model fingerprints are still checked.

Canonical storage is `state/assessments/<assessment_id>/report_state.json`, with immutable numbered snapshots in `revisions/`. Checkpoints are the existing pipeline operations: explicit unverified applicability context, query construction, retrieval/reranking, relevance gate, structured draft, separate citation/semantic validation, and publication. Stage 7 adds a conservative applicability analyst using cited explicit actor conditions and unverified profile facts; uncertain/tentative applicability still searches device evidence. Schema 3 reads schemas 1/2 without rewriting their archives or relabeling old findings as semantically checked. `audit_status=raw_spans_checked` establishes raw provenance only. Older `identifier_checked_only` and `legacy_unverified` findings retain their original limitations.

The assessment lock covers the whole review. Mutations require an expected revision and use a flushed temporary file in the same directory followed by atomic replacement. Another writer gets an actionable lock/revision error. A crashed process can leave `assessment.lock`; verify the recorded PID is no longer running before manually removing that lock. Locks are never automatically broken. Invalid/unsupported state schemas are rejected without overwriting the file. If disk writing is interrupted, canonical state determines the last committed checkpoint; the next mutation repairs a missing latest history snapshot before advancing.

Profile changes invalidate applicability and downstream operations; requirement/query changes invalidate query construction onward; source hashes, extraction settings, retrieval mode, candidate count, reranker backend changes invalidate retrieval onward; gate threshold/calibration changes invalidate the gate onward; generation model/context/prompt changes invalidate drafting onward. Reviewer prompt/schema/policy changes retain the draft and rerun citation and semantic validation. Completed reviewer output is bound to its generation call, full draft revision, requirement/applicability context, selected snapshots/ranges and reviewer configuration. Current query/prompt/gate/validation versions invalidate older checkpoints before reuse. Corpus changes invalidate **all** retrieval-dependent sections, even if the changed file was never cited. A targeted update recomputes only its selected section and marks other affected sections stale. Unchanged sections keep their findings, timestamps, section revisions and human annotations. Removed/renamed requirement IDs or a different legal document require a new assessment; old sections are not silently dropped. Saved calibration contents remain pinned until explicitly adopting another environment configuration. Ollama identities identify configured model tags rather than weight digests; refresh assessments if local weights change under the same tag.

Completed findings are exported to `state/assessments/<assessment_id>/assessment.json` and `assessment.md`. These are regenerated from canonical state at checkpoints; pending, failed and stale sections appear separately in the execution summary. Stale previous findings remain in state/history and are excluded from current finding counts and compatibility graphs. A successful command also refreshes the traditional `reports/assessment.json` and `reports/assessment.md` latest-report files. Exports have a separate writer lock and individual atomic file replacements; canonical state is authoritative if a crash interrupts the JSON/Markdown pair.

Historical rendering performs no live corpus checks or inference and labels the output **HISTORICAL**. It writes beneath a separate `historical-<revision>/` folder and leaves canonical state and latest exports untouched:

```powershell
python main.py report --assessment-id study01 --historical
python main.py report --assessment-id study01 --historical --revision 8
```

Use an actual saved state revision. A current `report` validates dependencies and persists any resulting staleness without calling a model. Unindexed file changes block current rendering/review; they never trigger an automatic index rebuild. Return to a validated live index explicitly, or render the historical snapshot.

To import an existing report, choose a **new** assessment ID:

```powershell
python main.py import-legacy --assessment reports/assessment.json --assessment-id legacy01
python main.py report --assessment-id legacy01 --historical
```

Import preserves source bytes, original IDs, statuses, timestamps, audit limitations and the original report in provenance. It marks findings `legacy_unverified` and keeps `human_validated=false`. A partial legacy report retains its missing-requirement count; it does not invent unseen requirements. Imported fingerprints are unknown, so current reuse requires recomputation against the existing register/index with `review --assessment-id legacy01 --resume`; migration alone does not verify findings. Existing canonical assessments cannot be overwritten by import.

New extractions derive IDs from legal source/hash, physical locator, provision, verified normalized quote and obligation position, independently of model-written paraphrases. Re-extracting a matching anchor retains existing (including legacy) IDs and versions changed wording in `requirement_revision`/`requirement_history`. The current extractor deduplicates identical quoted anchors; normalized positions are identity metadata, not verified raw quotation spans. Review state also preserves every previous published finding and its source/requirement snapshots in `finding_history`.

## Immutable source snapshots and exact quotations

Stage 2 uses schema-v2 assessment state. Schema-v1 files and revision history can be read without rewriting them; missing raw provenance stays unverified. The next explicit mutation writes schema v2 while archiving the original committed bytes. A schema upgrade does not turn an old finding into a newly verified one.

`mdr_rag/source_buffer.py` provides `add_passage(record)`, `get_passage(buffer_id)`, `resolve_quote(buffer_id, quote, offsets=None)` and `validate_link(link)`. Legal anchors and device passages use the same immutable representation. Snapshot identity covers chunk ID, corpus/source, file SHA-256, physical PDF page or text-block locator, exact indexed text/hash, extraction version and index format version. Editing a source creates a new snapshot; old snapshots cannot be replaced or removed by state mutations.

Each assessment embeds its `source_buffer`, so historical reports do not require the current index or original source files. Standalone extraction and `ask` snapshots are also retained at `state/source_buffer/SB-<content-hash>.json`. Their chat-call logs live in unique `state/evidence_runs/<operation>-<id>/trace.json` files. CLI evaluation uses the same recorder for optional LLM reranking. These artifacts contain source text and model drafts and must stay local/private. No automatic cleanup deletes old snapshots.

Three different records are kept:

- `retrieved_buffer_ids`: candidate passages returned by the retriever, including the candidate pool before optional reranking/top-k selection.
- `model_calls[].presented`: actual source ranges supplied to each structured chat call, with character offsets and a hash of the shown slice. Draft/answer device context is currently capped at 2,200 characters per passage; reranking/extraction may see a different set or range. Call instructions/input hashes, stage, model tag and started/completed/failed outcomes are recorded before inference. An interrupted call remains `started`, since completion is unknown.
- `claim_links`: verified quoted spans actually cited by model-written claims, bound to their draft call. `finding_history` retains the published revision's legal anchor and cited links. Candidate/presentation membership does not imply citation or semantic support.

New findings request `claims` with claim IDs/text and quoted source references. Unknown IDs, wrong corpus roles, empty claim inventories, invalid or ambiguous quotes and citations outside the specific draft's shown range cause `needs_review`. Rejected references remain in `draft_finding` for diagnosis and are omitted from published exact-quote links. Every supplied claim must have a valid cited span; independent completeness/semantic auditing of the prose remains Stage 6 work.

Raw offsets count Python characters in **exact indexed passage text**, not PDF bytes, original Word layout, or normalized text. The exact quotation must equal `passage.text[start:end]`. A quote appearing more than once requires explicit chosen offsets. New claim citations use this strict rule without case/whitespace normalization. The existing `core.is_real_quote` normalized validator is preserved for legacy extraction. `resolve_legacy_quote` separately maps case, whitespace, soft-hyphen and hyphen-normalized legal anchors back to a unique raw span; a successful mapping publishes the original raw substring, not the normalized proposal. Unmappable/ambiguous anchors are flagged. Reports suppress unverified legal quotations instead of presenting them as exact. Verified raw quotations are rendered in literal blocks that retain their whitespace.

This is deterministic provenance validation. A real quotation can still be irrelevant or fail to support its associated claim; `raw_spans_checked` is not an independent semantic audit, calibrated confidence or regulatory conclusion.

## Document upload, indexing and preview app

Install dependencies and start the local Streamlit interface:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Choose whether each upload belongs to the legal/regulatory or device collection, then click **Save selected files**. The app saves PDF, DOCX, TXT and Markdown files in `documents/legal/` or `documents/device/`, archives original revisions before updating existing filenames, lists files, and previews extracted text. Each upload is limited to 50 MiB. The app has no authentication; bind it to localhost as shown and do not expose it to a network.

In **Documents**, click **Index Documents** to index both folders using the existing local Ollama embedding model and `vector_db/`. Start Ollama and install the embedding model configured in `.env` first (default: `ollama pull embeddinggemma`). Saving files alone never makes them searchable. The status starts at **Not indexed** without a manifest, becomes **Index out of date** after saving, and displays **Ready** only when saved file hashes, archived provenance, embedding model, collection fingerprint and chunk count match. New, removed or changed files and a changed embedding model require indexing again. Existing indexes without a collection fingerprint require one rebuild. Status also shows indexed file/chunk counts, the last indexing time in UTC, the indexed embedding model and extraction warnings. An ordinary Streamlit rerun does not index documents.

Indexing is disabled without readable chunks. A scanned PDF produces an OCR warning; provide a text-readable copy. An unreadable legal source blocks indexing even if other documents contain text, while unreadable device sources are recorded with zero chunks and a warning. If indexing fails, check the model/server, document warnings and disk permissions, then click **Index Documents** again; developer logs contain exception details. `python main.py index` and `python main.py index --force-reembed` remain available and write the same compatible `state/manifest.json`.

Changed embeddings are prepared before publication; Chroma builds a staged collection and retains the previous collection as a backup. Embedding, candidate-write and promotion failures preserve the previous active index. Publication is **not atomic across Chroma renames and the manifest write**: an interruption can leave an absent active collection or a collection/manifest mismatch. Status detects these states and requires a retry, rather than reporting Ready. Successful indexing keeps backups in the same database; it does not delete them automatically. CLI and UI indexing share an exclusive `state/index.lock`; after a crashed writer, verify it has stopped before manually removing a leftover lock.

The offline acceptance test exercises PDF save, stale status, button indexing, Ready after restart, adding a second source, and indexing again with real PDF extraction and temporary Chroma storage; embedding inference is mocked. Run the targeted and complete suites:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_app_services.py tests/test_document_ui.py tests/test_ingestion.py
.venv/Scripts/python.exe -m pytest -q
```

### Ask Questions and inspect sources

After the index shows **Ready**, use **Ask Questions**. All documents from the verified manifest are selected initially. Use **Source collections** to choose all, legal only or device only, then **Indexed documents** to select any subset. Selecting no documents disables **Ask**. Missing or stale indexes block questions until rebuilt. Install both configured local models (`EMBEDDING_MODEL` and `OLLAMA_LLM_MODEL` in `.env`) and keep Ollama running; defaults are `embeddinggemma` and `qwen3:4b`.

Enter a question and click **Ask**. Dense retrieval applies the document filter in Chroma before top-k selection; BM25 ranks only the selected corpus, and reranking receives only selected passages. A source selection is part of the BM25 cache key. Identical filenames in legal and device folders remain distinct canonical source IDs. Single-chunk selections retain positive BM25 matching weights, avoiding the library's negative average-IDF edge case.

A **Supported** answer has passed the existing claim inventory, literal citation-span checks and local-model semantic review. Expand each **Verified cited source** to see its actual chunk ID, filename, physical PDF page or text block, and full indexed text. Only sources cited by accepted claim links appear here; retrieved but uncited candidates do not. Unknown source IDs, invented quotes, unreferenced claims or rejected support checks withhold the draft answer and citations. **Insufficient evidence** is distinct from errors such as an unavailable model or invalid structured output. Check the displayed retry guidance; exception details are logged for developers.

These checks use uploaded text only. Historical legal documents may omit amendments, and model-reviewed support is not a human audit or a compliance decision. Generation and verification treat documents and questions as untrusted input. Original files remain downloadable in **Document preview**. `python main.py ask "What records are required?"` uses the same typed Q&A engine and keeps its answer/citation output format.

This is single-turn Q&A. Only the latest result is kept in the current Streamlit session and redrawn on ordinary reruns without additional model calls. Changing document selection hides that result; a changed, invalid or rebuilt index clears it. There is no conversational context or chat-history UI. Existing audit snapshots, including questions and source excerpts, remain local under ignored `state/evidence_runs/` and `state/source_buffer/`.

Offline acceptance tests use two generated readable legal PDFs, a device DOCX, real parsing and temporary Chroma, with inference mocked. They submit questions through Streamlit, inspect actual source text, switch document selections, test abstention/errors, and check for duplicate requests. To verify with a live local model, index your sources, select one legal PDF, ask a question about a passage it contains, then ask for a fact absent from the selected text (for example an unrelated device's serial number). Expect a verified answer for supported claims or explicit abstention, and never a fabricated answer for the absent fact. Select only the device DOCX and repeat; all displayed sources must belong to the selection.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_question_services.py tests/test_query_retrieval.py tests/test_core.py tests/test_claim_audit.py
.venv/Scripts/python.exe -m pytest -q
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

An opt-in real-model smoke uses the first readable page of an uploaded legal PDF, real embeddings, two questions (one about printed text and one requesting an absent serial number), and isolated temporary storage. It fails on technical errors or a supported answer to the absent fact. It does not require a supported answer to the first question: conservative verification may abstain. Run with installed configured models; `QA_SMOKE_MODEL` optionally selects another installed chat model for this test only:

```powershell
$env:RUN_QA_SMOKE = "1"
# Optional, if intentionally testing another installed model:
# $env:QA_SMOKE_MODEL = "qwen3:1.7b"
.venv/Scripts/python.exe -m pytest -q -s tests/test_qa_smoke.py
Remove-Item Env:RUN_QA_SMOKE
```

---

# EU MDR 2017/745 regulatory evidence RAG (command line)

**Purpose:** Research-grade, auditable evidence mapping of a user-uploaded edition of the EU Medical Device Regulation (MDR) against user-supplied device documentation. NOT a conformity assessment, legal opinion, regulatory approval, or product-safety determination.

**Important:** MDR 2017/745 has been amended since its original 2017 publication. Analysis against the original 2017 text does NOT verify the current legal position. The program deliberately *does not* fetch amendments, harmonized standards, EUDAMED rules, or MDCG guidance. Only uploaded documents are examined. Verify law version, jurisdiction, device classification and applicability with a qualified regulatory specialist.

## 1. Requirements

- Python 3.11 or 3.12 on Windows, macOS, or Linux
- Ollama installed and running, with the models described in Quick start pulled locally
- Text-extractable source documents; scanned pages require separate OCR before ingestion
- Internet connectivity for initial Python package installation and model downloads

## 2. Put your files in their correct folders

```text
medical-device-rag/
  documents/
    legal/
      MDR_2017.pdf       <- Your uploaded original 2017 regulation
    device/
      technical_description.pdf
      risk_management_report.pdf
      clinical_evaluation.docx
    device_profile.json  <- Copy from device_profile.example.json, and edit
```

The app currently supports `.pdf`, `.docx`, `.txt` and `.md` for indexing, and **PDF** for page-scoped legal requirement extraction. PDF citations use **physical 1-based PDF page numbers**, which might not match printed Official Journal page numbers. DOCX citations use **text block indices**, not page numbers. Tables, figures, formulae, footnotes, and nested layouts might not be fully recovered. The output must be verified against the original files.

Create the device profile (change the fields to reflect the actual device, or leave unknown):

```powershell
Copy-Item device_profile.example.json documents/device_profile.json
```

## 3. Run the commands in order

**A. See PDF lengths and check if text can be extracted:**

```powershell
python main.py inspect
python main.py locate "ANNEX I"
python main.py locate "GENERAL SAFETY AND PERFORMANCE REQUIREMENTS"
```

The `locate` command returns *all* physical PDF pages with a text match (including references in the contents). Inspect the actual PDF viewer to find the desired Annex I span. Don't assume Annex I starts on the first match.

**B. Index all uploaded legal and device documents:**

```powershell
python main.py index
```

This clears and rebuilds the modular `medical_mdr_evidence` Chroma collection to avoid retaining removed passages. It saves SHA-256 checksums and extraction warnings to `state/manifest.json`.

**C. Test retrieval via question-answering:**

```powershell
python main.py ask "Which risk management documentation requirements appear in the uploaded MDR text, and what device documentation is available?"
```

**D. Create a DRAFT requirement register from SELECTED actual PDF pages:**

```powershell
python main.py extract --legal-file MDR_2017.pdf --pages "90-92"
```

`90-92` is **ONLY AN EXAMPLE**, not a claim about where any MDR provision occurs! Replace with page numbers from your exact PDF. The extractor considers all indexed text chunks on the selected pages and discards requirement candidates whose quoted source substring cannot be verified. Check `state/requirements_draft.json` and the `unreadable_selected_pages`/`rejected_unverifiable_quotes` fields.

**E. Compare every extracted requirement against device evidence:**

```powershell
python main.py review
```

Test with only 5 requirements first to limit local inference time:

```powershell
python main.py review --limit 5
```

Partial runs are explicitly marked in the resulting report. `review` uses the configured retrieval mode (hybrid by default) on the **device** corpus for EACH draft requirement, then generates one source-grounded structured assessment. No claim of exhaustive legal coverage is made: the chosen pages and the imperfect requirement extraction constrain coverage.

## 4. Output files

```text
vector_db/                    Local Chroma vector database
state/manifest.json           Indexed file hashes, warnings, model
state/requirements_draft.json Preliminary requirement register + legal citations
state/assessments/<id>/       Canonical review state, revisions and per-assessment exports
reports/assessment.json       Full machine-readable gap review + retrieved evidence
reports/assessment.md         Human-readable Q-Mix-style report
```

Finding statuses:
- `supported`: retrieved material directly addresses the requirement (NOT proof of legal compliance)
- `partial`: retrieved material addresses only part
- `not_found`: supporting evidence not found in retrieved passages (NOT proof of absence)
- `needs_review`: ambiguous or conflicting evidence
- `possibly_not_applicable`: applicability unresolved; specialist review required
- `insufficient_evidence`: no retained gate evidence or matching calibration; no claim that documentation is absent

Every candidate legal requirement stores source identity, file SHA-256, chunk ID, PDF page and draft applicability. New extraction also stores a verified raw legal span, or an explicit unresolved legacy anchor. Every verified claim citation records a content-addressed passage ID, file/text hashes, locator and exact character offsets. Missing, invented, ambiguous, unpresented or invalid citations produce `needs_review`; saving a retrieved passage alone does not make it evidence cited by a finding.

## 5. Why this implementation is RAG

1. `core.py`: extracts source text and creates traceable chunks.
2. `search.py`: embeds chunks with the configured local Ollama embedding model, stores vectors in ChromaDB; retrieval merges dense semantic ranking with BM25 lexical ranking using reciprocal-rank fusion.
3. `pipeline.py:extract_requirements`: prompts an LLM per chunk of the selected MDR pages, validates a verbatim quote against its source, and builds a structured draft requirement register.
4. `pipeline.py:run_review` delegates to `review_state.py`: retrieves and gates device evidence per requirement, generates drafts only from retained passages, validates raw spans and atomic-coverage inventories and saves each checkpoint through `report_state.py`. Completed stages are reused only after dependency validation.
5. `Q_Mix_report_writer.py`: deterministic template report built from source-anchored findings, not an autonomous legal agent.

## 6. Safe development and verification

```powershell
python -m pytest -q
```

The tests check page scoping, source quote verification, chunk sizes, fabricated citation filtering, and report generation. They do NOT replace an MDR domain expert review or a full end-to-end run against real documents. This distribution does not include the copyrighted/official MDR PDF or actual device records; supply them separately. Ollama inference runs locally; downloading Python packages and Ollama models requires internet access.

### Limitations before using for real regulatory work

- User has to decide which physical PDF pages form the complete relevant scope. The original MDR's all-article/all-annex obligations are not exhaustively classified automatically.
- No automatic updates or consolidation of legal amendments, MDCG guidance, harmonized standards, conformity assessment routes, or country-specific rules.
- LLM requirement extraction may miss obligations, split cross-page requirements, or misidentify applicability.
- Document parsing misses/garbles some tables and images, and cannot OCR scanned PDFs.
- No automatic device classification or legal jurisdiction decision. Device profile is self-declared and unverified.
- Hybrid retrieval reduces but does not eliminate false negatives. High-stakes decisions need primary-document review.
- No access control/encryption/multi-tenancy, calibrated uncertainty, clinical validation, or production audit governance.
- Output is a *research assistant's evidence map*, not a declaration of conformity or substitute for QA/RA review.

## 7. FAQ

**What is Q-Mix_report_writer?** No public interface was supplied for that name. This project contains an explicitly local `mdr_rag/Q_Mix_report_writer.py` implementing a report writer. It is NOT a verified integration to a separate library/service. If you upload the real writer code or its API specification, its adapter can be implemented accurately.

**Why can't I just ask 'Is it MDR compliant?'** A one-shot query cannot guarantee completeness, applicability, evidence quality, or current legal validity. The extraction -> independent retrieval -> evidence assessment -> human review approach is a safer starting point.

**Do I need Streamlit?** No. All tasks run in the command line and output JSON/Markdown.

**Can I use the original 2017 MDR for today's compliance?** Not alone. You would need to incorporate amendments, current consolidated version, relevant harmonized standards, guidance, and applicable additional rules, and verify them professionally.

---

# RAG Evaluation Upgrade (v2): interactive embeddings, retrieval benchmark and graph

**This evaluation measures evidence retrieval and documented citation relationships, NOT whether a medical device is legally compliant.** It is an extension of the original v1 CLI project. All input documents, the `.env` file, and the existing indexed vector database remain local to this project's folder (unless you deliberately copy them).

For a new corpus, place medical-device files and your MDR PDF as in the preceding sections, then build the index. Skip this step when evaluating an unchanged existing index:

```powershell
python main.py index
```

### A. Embedding visualization: no new embeddings required

```powershell
python main.py visualize-embeddings --sample 600
```

Creates `reports/embeddings.html` (open in your browser) and `reports/embeddings.json` (embedding health metrics). This reads **already stored embeddings** from Chroma and projects unit-normalized vectors using PCA. Hover points for chunk IDs, source files, pages and short excerpts. It computes embedding dimensionality, counts, suspiciously high-similarity pairs among the sampled vectors, and PCA explained variance.

To embed one **new search query** and inspect its 10 closest sampled neighbors using cosine similarity:

```powershell
python main.py visualize-embeddings --sample 600 --query "risk management verification"
```

Only the query is newly embedded; the documents are not re-embedded. Note: this query's nearest neighbors are among the *sampled* document vectors, not necessarily the full corpus. PCA compresses a much higher-dimensional embedding space; 2D distances are not reliable semantic relevance scores and semantic similarity is not legal compliance.

### B. Build a manually labeled question set (gold ground truth)

Start by exploring passages:

```powershell
python main.py explore "risk management file" --kind legal --k 12
python main.py explore "clinical evaluation report" --kind device --k 12
```

The CLI shows top-ranked chunk IDs, actual source names and physical PDF page numbers. **Manually open the original PDFs** to decide which pages or chunks actually answer the question. Do not assume top-ranked pages are correct; otherwise evaluation would reward the system for its own errors.

Edit `eval/gold_queries.json` (initially `[]`) to contain at least one human-verified entry; ideally annotate 20–50 questions of varying difficulty and across both corpora.

```json
[
  {
    "id": "Q1",
    "query": "What risk management obligations apply?",
    "kind": "legal",
    "relevant": [
      {"source": "legal/MDR_2017.pdf", "page": 90}
    ]
  }
]
```

**Page 90 is a deliberately illustrative placeholder, not a verified MDR page.** Replace filenames/page numbers with real sources before running. Multiple relevant labels can be supplied per query. For more precise ground truth, add `"chunk_id": "L-..."` to a label copied from `explore`: this requires the exact chunk ID, source, and optional page to match, but IDs change after re-indexing changed content. Page-level relevance can overestimate retrieval correctness when a page contains multiple unrelated chunks. `page: null` is allowed for document-level labels, but these are even coarser.

### C. Compare dense, BM25 and hybrid retrieval

```powershell
python main.py evaluate --gold eval/gold_queries.json --ks 3 5 10
```

Creates JSON and Markdown under a distinct `reports/evaluation-<run_id>/` directory by default. `--out` chooses an explicit new path; existing artifacts are never overwritten. Outputs contain IDs/hashes/metrics rather than source excerpts, query prose or model claim text.

**Metrics**: `Recall@k` = distinct relevant human-labeled source pages/chunks retrieved in top k / total relevant labels. `Precision@k` = distinct relevant labels retrieved in top k / k. `HitRate@k` = fraction of questions with at least one labeled hit. `MRR@k` = mean inverse rank of the earliest labeled hit. `nDCG@k` = normalized discount-weighted ranking quality using one credit per distinct relevant label. Dense uses the vector index, BM25 lexical matches, and hybrid uses the same reciprocal-rank fusion formula as the app. Evaluation uses the production candidate/fusion/reranker pipeline with explicit per-query/backend and merged budgets. For reproducibility reports include indexed file hashes and embedding model ID.

**Interpretation**: Scores are about how well the system finds *annotated* evidence. They are not answer accuracy, citation faithfulness, legal coverage, regulatory applicability or compliance. Use a held-out test set and human adjudication. Always report question count, label granularity, and confidence/uncertainty rather than making claims from a handful of questions.

For `ask`, substantive answer text is rendered from the generation-time structured claim inventory and shown only when it includes at least one source ID matching a retrieved passage and a second local-model pass reviews every claim ID exactly once. Each claim must include a passage ID and an exact raw quote inside the text range shown to the model; repeated quotations require explicit offsets. The normalized matcher remains available for legacy extraction, while `ask` uses raw character spans; unsupported claims, invented IDs, unverifiable quotes, or an empty claim audit make the CLI abstain. This is an additional model-based check, not a proof of entailment or a guarantee against mistakes.

Add `--rerank` before the command to compare the hybrid candidate ranking with local LLM reranking:

```powershell
python main.py --rerank evaluate --gold eval/gold_queries.json --ks 3 5 10
```

The reranked methods are `hybrid_llm` or `hybrid_cross_encoder`, with explicit backend identity. They reorder at most 30 production merged candidates and cannot recover omitted passages. The current `eval/gold_queries.json` must contain human-verified labels before the benchmark can run; `gold_queries.EXAMPLE.json` contains placeholders only. Do not interpret synthetic test fixtures as project performance.

### D. Generate a requirement-evidence provenance graph

First run the original regulatory extraction and review commands:

```powershell
python main.py extract --legal-file MDR_2017.pdf --pages "REPLACE_WITH_VERIFIED_PAGES"
python main.py review --limit 5
python main.py graph
```

The `--pages` option must be replaced with actual physical PDF pages, for example `"101-103"`, **only if those are verified pages in your copy**.

Produces `reports/evidence_graph.html` and `reports/evidence_graph.json`. The graph links:

- Requirement nodes (colored by evidence status or pending/failed/stale execution state)
- Source chunk nodes (cited, identifier-validated passages, plus explicitly distinguished retrieval/raw/audit relations)
- Device document nodes (containing the cited chunks)

The JSON quantifies requirements with/without cited evidence, number of distinct evidence chunks, linked document count, and invalid citation IDs. **An edge means the finding cited that excerpt, not that the excerpt legally fulfills the requirement.** `citation_coverage_fraction` is not a compliance percentage. A `--limit` review is partial; a full assessment is required before considering full extracted-requirement coverage.

The graph summarizes all requirements but, by default, draws only the first 140 requirement nodes and their neighbors to keep browser performance reasonable. Use `--max-requirements 250` to change the rendered subset.

## Production comparisons and CPU reproducibility (Stage 8)

Use `eval/production_gold.EXAMPLE.json` as a worksheet, not gold. The preferred envelope records `schema_version=1`, `dataset_type=human_gold|synthetic|unverified`, `human_validated`, reviewer, legal-version label, full corpus `sources_sha256` and cases. Human gold requires explicit reviewer validation and source/version hashes matching the current corpus. Legacy lists remain readable but are labeled **unverified legacy**. Synthetic fixtures cannot claim human validation. `answerable=false` explicitly requires `relevant=[]`; missing/malformed positive labels remain errors. No-positive recall, MRR, nDCG and hit rate are null and excluded from positive-denominator aggregates.

Each case has `id`, `query`, `kind`, `split=calibration|held_out|unspecified`, answerability and relevant source/page/chunk labels. Full-pipeline cases also need a distinct actual `requirement_id` and device kind. Optional `passage_labels` contain unique `chunk_id`, `source`, `file_sha256` and boolean `relevant`; annotate positives and hard negatives independently. A passage may be useful/partially relevant even when the complete question is unanswerable: passage labels are separate from fully answering `relevant` labels. Passage precision is reported only when every measured passage has a human label; unknown passages are not silently negative. Questions and registered requirements cannot receive repeated votes or cross splits. Held-out aggregate metrics exclude calibration cases; unspecified legacy splits are exploratory. Ineligible full-pipeline cases are listed as excluded, not execution failures.

```powershell
python main.py evaluate --gold eval/reviewed_gold.json --compare-all --ks 3 5 10 --run-id cpu_holdout_01 --out reports/cpu_holdout_01/evaluation.json
# Explicit independent none/LLM policies:
python main.py evaluate --gold eval/reviewed_gold.json --methods complete_pipeline_none complete_pipeline_llm --run-id backend_policy_01
# BM25 alone calls neither embedding nor reranking services:
python main.py evaluate --gold eval/reviewed_gold.json --methods bm25 --run-id lexical_01
```

The six comparisons are `dense`, `bm25`, `hybrid`, `multi_query_hybrid`, `multi_query_cross_encoder` and `complete_pipeline_cross_encoder`. Single-query methods use one query; multi-query methods use at most four deterministic production intents. Every query/backend has a 12-candidate cap; merged/reranked pools cap at 30. Thus multi-query has a larger search-call budget, recorded explicitly. All retrieval methods return the merged pool before calculating top-k metrics. Full evaluation invokes the production six-role review against an existing register under fresh `eval-<run_id>-...` assessment IDs, records private canonical snapshots, and leaves the user's latest compatibility report untouched. It does not extract or rebuild an index.

Outputs track Recall/nDCG/MRR@k, pre-rerank candidate recall, annotated passage precision/annotation coverage, gate evidence retention versus final answerable-finding retention, unanswerable abstention, citation-ID/raw-span validity, published citation validity, reviewer inventory coverage, failures and median/p95 stage/method latency. Reviewer coverage measures claim IDs, not semantic correctness. A genuine quote can pass raw-span validation while the reviewer withholds the finding. Technical retrieval/scorer/reviewer failures are counted separately and never become successful abstentions. Strict uncalibrated/mismatched gating remains visible; disabled gating cannot count as strict validation.

Human claim support and contradiction misses are **not measured by the model itself**. After independently reading the original sources and every published claim, create `eval/grounding_labels.EXAMPLE.json` with actual verdicts and bindings from the frozen evaluation. The example is intentionally invalid until completed. Evaluation claim IDs are opaque SHA-256 aliases (`CL-...`); compute `mdr_rag.experiments.public_claim_id(canonical_claim_id)` to match them to the private canonical inventory. This prevents a model from leaking prose through its chosen ID. Labels must cover every published claim case/alias exactly once and match the evaluation fingerprint, assessment revision, claim revision and source-context hash. Offline adjudication reads immutable assessment revisions and makes no inference calls:

```powershell
python main.py evaluate --saved-evaluation reports/cpu_holdout_01/evaluation.json --grounding-labels eval/reviewed_claim_labels.json --out reports/cpu_holdout_01/grounding.json
```

For repeatable CPU experiments, keep the existing pinned cross-encoder revision, CPU float32, four scorer threads, batch size four, 512 combined tokens and query-prefix limit 128. `OLLAMA_NUM_GPU=0` additionally requests zero GPU layers in generation, embedding and LLM-reranking calls; blank preserves automatic device selection. The installed SDK accepts this option, but verify the server's actual execution before claiming CPU-only measurements. Reports distinguish requested settings from unverified actual Ollama device/model digests. Preserve `qwen3:4b`, `embeddinggemma`, context 8192 and the uploaded legal-version label unless deliberately comparing them; these are defaults, not measured optimal settings. Record OS/Python/libraries, model revisions, prompt hashes, corpus hashes, context/token limits and warm/cold cache conditions. Fixed experiment order and cache/model warm-up affect latency. Python peak allocations exclude native tensors; optional process RSS/lifetime peak excludes the Ollama server and is not a per-stage model-memory measurement.

Use supported controls: `CROSS_ENCODER_MODEL`, `CROSS_ENCODER_REVISION`, `CROSS_ENCODER_BATCH_SIZE`, `CROSS_ENCODER_MAX_TOKENS` and `RETRIEVAL_MAX_CANDIDATES`, rather than the proposed `RERANK_MODEL`, `RERANK_DEVICE`, `RERANK_BATCH_SIZE` or `RERANK_MAX_CANDIDATES` names. Cross-encoder execution is fixed to CPU; repair is hard-bounded at one attempt per section draft cycle, so `REVIEW_MAX_REPAIRS` is not an environment control. The shared multi-query and gate settings are already validated. Keep `EVIDENCE_GATE_CALIBRATION` absent until independent calibration labels produce an artifact; never add a placeholder threshold file to make strict mode proceed. None has no relevance scorer: strict mode abstains without calibration, experimental score gating errors, and an intentionally disabled gate is explicit. LLM relevance can be experimental or disabled; its mutable model tag cannot create the current strict calibration artifact.

Label 20?50 diverse cases where qualified human review is feasible, including unanswerable/ambiguous cases, legal qualifiers/exceptions, cross-document evidence, historical differences and source injection. Report actual split/sample counts. Small splits are exploratory. Real Stage 8 measurements are currently blocked by an empty gold set and index/source mismatch; see [the honest evaluation report](docs/stage8_evaluation_report.md). No threshold, accuracy, latency or peak model-memory performance claim was fabricated.

## Recommended research experiments

1. Establish a fixed, human-labeled test set spanning common, complex, negative, and ambiguous queries.
2. Run the benchmark as a baseline; track scores and errors in JSON across runs.
3. Compare chunk sizes 700/1200/2000 characters, preserving requirement/section boundaries whenever possible. The current chunker is character-based and needs structure-aware legal segmentation for production.
4. Compare dense search, BM25, hybrid retrieval and optional reranking by the *same held-out* gold questions; never change labels to fit the algorithm.
5. Audit generated answers separately for citation attribution, hallucinations, omitted legal clauses, applicability mistakes and refusals when evidence is insufficient.
6. When using newer amendments, index legal version/effective date as metadata and require temporal and jurisdictional filtering before retrieval.
7. For future **GraphRAG**, build a reviewed legal ontology (Articles -> Annex sections -> requirements -> supporting device evidence) and use bounded graph traversal during retrieval. The v2 graph is a **visualization of verified citation IDs**, not GraphRAG-based retrieval.

**Confidentiality:** local Plotly HTML/JSON exports contain document names and passage excerpts. Treat reports as sensitive and do not publish them without authorization.

### Offline visual preview, even before you upload documents

Open the **SYNTHETIC DEMO ONLY** HTML files in `eval/` to preview the interactive chart types. All demo metrics and example texts are fictional and do not characterize your real MDR. The real `reports/` outputs are produced only when you run the commands against indexed documents.
