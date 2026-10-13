# Medical Device RAG

The supported application uses **Ollama locally** for embeddings and structured language-model tasks. The supported entry points are `main.py` (CLI) and `streamlit_app.py` (document upload and preview); shared application code is in `mdr_rag/`. These workflows do not require OpenAI or Gemini API keys.

`rag.py` is a separate, older Gemini prototype retained for reference, not the supported application. It imports `mdr_rag.tls` and `mdr_rag.quota`, which are not present in this checkout, and expects Gemini dependencies and credentials not used by the modular app. Do not use it for the supported workflow; use `main.py` instead. The script is retained in place and has not been run, so its separate Chroma collection/index has not been changed.

## Quick start

### Windows (PowerShell)

Install and start Ollama, then run:

```powershell
ollama pull embeddinggemma
ollama pull qwen3:4b
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
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
cp .env.example .env
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

Changing `EMBEDDING_MODEL` requires `python main.py index` again. Model execution is local, but review your own confidentiality/security requirements.

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
mdr_regulatory_rag/
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

This clears and rebuilds the entire local Chroma collection to avoid retaining removed passages. It saves SHA-256 checksums and extraction warnings to `state/manifest.json`.

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

Test with only 5 requirements first to control costs:

```powershell
python main.py review --limit 5
```

Partial runs are explicitly marked in the resulting report. `review` uses dense+BM25 hybrid retrieval on the **device** corpus for EACH draft requirement, then generates one source-grounded structured assessment. No claim of exhaustive legal coverage is made: the chosen pages and the imperfect requirement extraction constrain coverage.

## 4. Output files

```text
vector_db/                    Local Chroma vector database
state/manifest.json           Indexed file hashes, warnings, model
state/requirements_draft.json Preliminary requirement register + legal citations
reports/assessment.json       Full machine-readable gap review + retrieved evidence
reports/assessment.md         Human-readable Q-Mix-style report
```

Finding statuses:
- `supported`: retrieved material directly addresses the requirement (NOT proof of legal compliance)
- `partial`: retrieved material addresses only part
- `not_found`: supporting evidence not found in retrieved passages (NOT proof of absence)
- `needs_review`: ambiguous or conflicting evidence
- `possibly_not_applicable`: applicability unresolved; specialist review required

Every candidate legal requirement stores: uploaded filename, SHA-256 hash, source chunk ID, exact quote, PDF page, and draft applicability. Every reported device citation stores filename, PDF page / text block, SHA-256, and exact retrieval ID. The program drops invented reference IDs, and downgrades unreferenced `supported`/`partial` outputs to `needs_review`.

## 5. Why this implementation is RAG

1. `core.py`: extracts source text and creates traceable chunks.
2. `search.py`: embeds chunks with the configured local Ollama embedding model, stores vectors in ChromaDB; retrieval merges dense semantic ranking with BM25 lexical ranking using reciprocal-rank fusion.
3. `pipeline.py:extract_requirements`: prompts an LLM per chunk of the selected MDR pages, validates a verbatim quote against its source, and builds a structured draft requirement register.
4. `pipeline.py:run_review`: retrieves device evidence for each individual requirement, prompts the LLM with ONLY that requirement + retrieved passages, validates IDs, and saves structured findings.
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

Place medical-device files and your MDR PDF as in the preceding sections, then build or refresh the index:

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

**Metrics**: `Recall@k` = distinct relevant human-labeled source pages/chunks retrieved in top k / total relevant labels. `Precision@k` = distinct relevant labels retrieved in top k / k. `HitRate@k` = fraction of questions with at least one labeled hit. `MRR@k` = mean inverse rank of the earliest labeled hit. `nDCG@k` = normalized discount-weighted ranking quality using one credit per distinct relevant label. Dense uses the vector index, BM25 lexical matches, and hybrid uses rank fusion matching the app's search strategy. For reproducibility reports include indexed file hashes and embedding model ID.

**Interpretation**: Scores are about how well the system finds *annotated* evidence. They are not answer accuracy, citation faithfulness, legal coverage, regulatory applicability or compliance. Use a held-out test set and human adjudication. Always report question count, label granularity, and confidence/uncertainty rather than making claims from a handful of questions.

For `ask`, the generated answer is shown only when it includes at least one source ID matching a retrieved passage and a second local-model pass finds support for every factual claim. Each claim must include a passage ID and an exact quote that is present in that passage; unsupported claims, invented IDs, unverifiable quotes, or an empty claim audit make the CLI abstain. This is an additional model-based check, not a proof of entailment or a guarantee against mistakes.

Add `--rerank` before the command to compare the hybrid candidate ranking with local LLM reranking:

```powershell
python main.py --rerank evaluate --gold eval/gold_queries.json --ks 3 5 10
```

The reranked method is named `hybrid_reranked`. It only reorders the top `max(3 * max(k), 12)` hybrid candidates, so it cannot recover evidence omitted by the first-stage retriever. The current `eval/gold_queries.json` must contain human-verified labels before the benchmark can run; `gold_queries.EXAMPLE.json` contains placeholders only. Do not interpret synthetic test fixtures as project performance.

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
