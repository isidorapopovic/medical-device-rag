# Medical Device RAG

The supported application uses **Ollama locally** for embeddings and structured language-model tasks. The supported entry points are `main.py` (CLI) and `streamlit_app.py` (document upload and preview); shared application code is in `mdr_rag/`. These workflows do not require OpenAI or Gemini API keys.

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

Changing `EMBEDDING_MODEL` requires an intentional index rebuild before using that model with existing data. `index` deletes and recreates the modular collection; do not run it just to verify an existing baseline. Model execution is local, but review your own confidentiality/security requirements.

## Local configuration and baseline checks

`.env.example` lists the local settings read by the modular app, including: `EMBEDDING_MODEL=embeddinggemma`, `OLLAMA_LLM_MODEL=qwen3:4b`, `OLLAMA_NUM_CTX=8192`, `RETRIEVAL_MODE=hybrid`, `RERANK_ENABLED=false`, and `LEGAL_VERSION=UNSPECIFIED HISTORICAL TEXT`. These are app defaults, not performance guarantees. `LEGAL_VERSION` is a user-supplied label, not a verified legal edition. `OLLAMA_NUM_CTX` must be a positive integer supported by your local model. Retrieval accepts `dense`, `bm25`, or `hybrid`; reranking accepts `true` or `false`. CLI overrides take precedence; otherwise process environment variables take precedence over `.env`, then code defaults apply. The setup commands above preserve an existing `.env`.

After activating the project virtual environment, `python main.py --help` needs installed Python dependencies but no Gemini credentials or inference. Run `python -m pytest -q` for API-free tests. If Windows temp-folder permissions block pytest, use a fresh writable directory, for example `python -m pytest -q --basetemp reports/test-temp-stage0`. Pytest clears the chosen directory, so always choose a dedicated test-only path.

Reviews now have persistent assessment IDs. Use `python main.py review --assessment-id baseline01 --limit 2` for a distinct review; evaluation supports `python main.py evaluate --gold eval/gold_queries.json --out reports/baseline01/retrieval_evaluation.json`. Reviews require matching existing state/index and installed local models; evaluation also requires real human-verified gold labels. Do not use illustrative labels as measurements. The dated [Stage 0 baseline](docs/stage0_baseline.md) records the original availability blockers; [Stage 1 verification](docs/stage1_verification.md) records persistence tests; [Stage 2 verification](docs/stage2_verification.md) records raw-span provenance tests; [Stage 3 verification](docs/stage3_verification.md) records bounded query planning and retrieval tests; [Stage 4 verification](docs/stage4_verification.md) records backend and CPU model checks.

## Bounded review query planning

Reviews default to `MULTI_QUERY_ENABLED=true`: the original obligation query plus up to three artifact, process/test and requirement/profile qualifier intents. Expansions use obligation text and explicitly supplied device name/intended purpose; they do not infer legal obligations or classification. `QUERY_PLANNER=deterministic` is the default. Optional `QUERY_PLANNER=llm` lets the local model select from this sourced menu; malformed JSON or unknown selections use deterministic templates and save a fallback reason. The original query is always retained. `ask` remains a single-query command.

`MULTI_QUERY_MAX=4`, `RETRIEVAL_PER_QUERY=12`, and `RETRIEVAL_MAX_CANDIDATES=30` are hard upper bounds (each may be reduced). Each query retrieves at most 12 candidates per selected backend. Reciprocal-rank fusion first combines dense/BM25 lists within each query, then combines query lists. Duplicate query texts and chunk IDs receive no extra votes within a list; ties use chunk ID. Raw vector distances and BM25 scores are never summed. The merged pool is capped at 30 before optional reranking against the original query plus explicitly supplied essential profile qualifiers; `--k` selects final passages and accepts 1..30. Tokenization/BM25 construction is cached in memory by database, corpus kind and manifest fingerprint for reviews, with four cached corpora at most.

Canonical sections and finding history save `query_plan` and `retrieval_trace`: per-query candidate lists, query/backend ranks, fused pool and selected IDs. Retrieved candidates are separately snapshotted, model calls record actual presented ranges, and findings keep validated cited spans. Retrieval provenance is not evidence that a model saw or cited every candidate. Older schema-2 reports load with these optional fields absent; changed query/retrieval versions invalidate reuse without rewriting historical snapshots. Planning settings invalidate query construction onward; candidate budgets invalidate retrieval onward. With LLM planning, model/context changes also invalidate planning. `MULTI_QUERY_ENABLED=false` retains single-query retrieval. Reranked reviews still record candidate and score diagnostics; the unreranked compatibility path omits that trace.

The existing `evaluate` command still benchmarks its separate single-query implementation. Its scores do not measure Stage 3 expansions or the new candidate budgets. Use the deterministic tests as behavior checks, not performance measurements.

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

Cross-encoder relevance scores are not evidence sufficiency, compliance probabilities or calibrated legal confidence. Applying a sigmoid would not change that. The initial CPU latency/memory observations and opt-in smoke command are in [Stage 4 verification](docs/stage4_verification.md); benchmark on your own corpus before selecting a default. The existing `evaluate` command can select the backend and logs its identity/scores, while retaining its separate single-query retrieval implementation and the compatibility method name `hybrid_reranked`.

## Persistent reviews, resume and updates

The existing requirement register is reused; resume never runs extraction. Start a named assessment, continue it, or refresh one actual requirement ID from the register:

```powershell
python main.py review --assessment-id study01 --limit 2
python main.py review --assessment-id study01 --resume
python main.py review --assessment-id study01 --requirement-id R-ACTUAL-ID --refresh
python main.py report --assessment-id study01
```

A review without `--assessment-id` generates a new ID and prints it. Reusing an existing ID requires `--resume` or `--requirement-id`. `--resume` continues pending/failed/stale sections; `--requirement-id` processes only the named section if unfinished or stale, and `--refresh` deliberately starts a new finding revision for that section. It cannot be combined with `--resume`. `--limit` must be positive and cannot be combined with a requirement ID; on resume it selects the first N entries of the full register, skipping already completed entries. An omitted `--k` reuses the saved value (new assessments default to 7). Environment/model settings and explicit CLI overrides are checked against saved dependencies; a changed setting invalidates the affected stages rather than mixing configurations.

Canonical storage is `state/assessments/<assessment_id>/report_state.json`, with immutable numbered snapshots in `revisions/`. Checkpoints are the existing pipeline operations: explicit unverified applicability context, query construction, retrieval, structured draft, and raw-span provenance validation/publication. Stage 2 adds exact source spans and context membership; an applicability analyst, independent semantic reviewer and evidence gate remain pending. `audit_status=raw_spans_checked` establishes raw provenance only. Older `identifier_checked_only` and `legacy_unverified` findings retain their original limitations.

The assessment lock covers the whole review. Mutations require an expected revision and use a flushed temporary file in the same directory followed by atomic replacement. Another writer gets an actionable lock/revision error. A crashed process can leave `assessment.lock`; verify the recorded PID is no longer running before manually removing that lock. Locks are never automatically broken. Invalid/unsupported state schemas are rejected without overwriting the file. If disk writing is interrupted, canonical state determines the last committed checkpoint; the next mutation repairs a missing latest history snapshot before advancing.

Profile changes invalidate applicability and downstream operations; requirement/query changes invalidate query construction onward; source hashes, extraction settings, retrieval mode, candidate count, reranker backend or calibration identity changes invalidate retrieval onward; generation model/context/prompt changes invalidate drafting onward. Validation-version changes retain the draft and rerun provenance checks. The Stage 2 query/prompt versions invalidate older checkpoints before raw provenance is reused. Corpus changes invalidate **all** retrieval-dependent sections, even if the changed file was never cited. A targeted update recomputes only its selected section and marks other affected sections stale. Unchanged sections keep their findings, timestamps, section revisions and human annotations. Removed/renamed requirement IDs or a different legal document require a new assessment; old sections are not silently dropped. Fingerprints identify configured model tags, not Ollama weight digests; refresh assessments if local weights change under the same tag.

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

## Document upload and preview app

Install dependencies and start the local Streamlit interface:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Choose whether each upload belongs to the legal/regulatory or device collection. The app saves supported PDF, DOCX, TXT and Markdown files in `documents/legal/` or `documents/device/`, lists existing files, and previews extracted text. Uploading does not build the search index; run `python main.py index` after adding documents before querying them. Existing files are never overwritten: rename a new upload if its filename is already present. Each file is limited to 50 MiB. The app has no authentication; bind it to localhost as shown and do not expose it to a network.

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

Every candidate legal requirement stores source identity, file SHA-256, chunk ID, PDF page and draft applicability. New extraction also stores a verified raw legal span, or an explicit unresolved legacy anchor. Every verified claim citation records a content-addressed passage ID, file/text hashes, locator and exact character offsets. Missing, invented, ambiguous, unpresented or invalid citations produce `needs_review`; saving a retrieved passage alone does not make it evidence cited by a finding.

## 5. Why this implementation is RAG

1. `core.py`: extracts source text and creates traceable chunks.
2. `search.py`: embeds chunks with the configured local Ollama embedding model, stores vectors in ChromaDB; retrieval merges dense semantic ranking with BM25 lexical ranking using reciprocal-rank fusion.
3. `pipeline.py:extract_requirements`: prompts an LLM per chunk of the selected MDR pages, validates a verbatim quote against its source, and builds a structured draft requirement register.
4. `pipeline.py:run_review` delegates to `review_state.py`: retrieves device evidence per requirement, generates structured drafts, validates raw spans and saves each checkpoint through `report_state.py`. Completed stages are reused only after dependency validation.
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

Creates `reports/retrieval_evaluation.json` (aggregate and per-question metrics, missed gold labels, top-k passages) and `reports/retrieval_evaluation.html` (interactive performance curves).

**Metrics**: `Recall@k` = distinct relevant human-labeled source pages/chunks retrieved in top k / total relevant labels. `Precision@k` = distinct relevant labels retrieved in top k / k. `HitRate@k` = fraction of questions with at least one labeled hit. `MRR@k` = mean inverse rank of the earliest labeled hit. `nDCG@k` = normalized discount-weighted ranking quality using one credit per distinct relevant label. Dense uses the vector index, BM25 lexical matches, and hybrid uses the same reciprocal-rank fusion formula as the app. Evaluation currently has a separate retrieval implementation; candidate limits and tie handling can differ from production search. For reproducibility reports include indexed file hashes and embedding model ID.

**Interpretation**: Scores are about how well the system finds *annotated* evidence. They are not answer accuracy, citation faithfulness, legal coverage, regulatory applicability or compliance. Use a held-out test set and human adjudication. Always report question count, label granularity, and confidence/uncertainty rather than making claims from a handful of questions.

For `ask`, the generated answer is shown only when it includes at least one source ID matching a retrieved passage and a second local-model pass finds support for every factual claim. Each claim must include a passage ID and an exact raw quote inside the text range shown to the model; repeated quotations require explicit offsets. The normalized matcher remains available for legacy extraction, while `ask` uses raw character spans; unsupported claims, invented IDs, unverifiable quotes, or an empty claim audit make the CLI abstain. This is an additional model-based check, not a proof of entailment or a guarantee against mistakes.

Add `--rerank` before the command to compare the hybrid candidate ranking with local LLM reranking:

```powershell
python main.py --rerank evaluate --gold eval/gold_queries.json --ks 3 5 10
```

The reranked method is named `hybrid_reranked`. It only reorders up to `min(30, max(3 * max(k), 12))` hybrid candidates, so it cannot recover evidence omitted by the first-stage retriever. The current `eval/gold_queries.json` must contain human-verified labels before the benchmark can run; `gold_queries.EXAMPLE.json` contains placeholders only. Do not interpret synthetic test fixtures as project performance.

### D. Generate a requirement-evidence provenance graph

First run the original regulatory extraction and review commands:

```powershell
python main.py extract --legal-file MDR_2017.pdf --pages "REPLACE_WITH_VERIFIED_PAGES"
python main.py review --limit 5
python main.py graph
```

The `--pages` option must be replaced with actual physical PDF pages, for example `"101-103"`, **only if those are verified pages in your copy**.

Produces `reports/evidence_graph.html` and `reports/evidence_graph.json`. The graph links:

- Requirement nodes (colored by the LLM-assigned evidence status)
- Source chunk nodes (cited, identifier-validated passages only)
- Device document nodes (containing the cited chunks)

The JSON quantifies requirements with/without cited evidence, number of distinct evidence chunks, linked document count, and invalid citation IDs. **An edge means the finding cited that excerpt, not that the excerpt legally fulfills the requirement.** `citation_coverage_fraction` is not a compliance percentage. A `--limit` review is partial; a full assessment is required before considering full extracted-requirement coverage.

The graph summarizes all requirements but, by default, draws only the first 140 requirement nodes and their neighbors to keep browser performance reasonable. Use `--max-requirements 250` to change the rendered subset.

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
