# 01 — Streamlit Document Indexing (P0)

## Codex role and objective
Act as a senior Python engineer. Work inside `medical-device-rag` on a feature branch. Implement a fully functional **Index Documents** workflow in the existing Streamlit application. Do not rewrite the RAG stack.

## Read before editing
Inspect `streamlit_app.py`, `mdr_rag/document_ui.py`, `mdr_rag/core.py`, `mdr_rag/search.py`, `mdr_rag/pipeline.py`, `main.py`, `requirements.txt`, `.env.example`, and tests. Confirm APIs against checked-out branch; do not assume GitHub `main` matches local checkout. Keep existing local-only deployment and the 50 MiB upload limit.

## Confirmed starting point (GitHub main, October 2026)
- `streamlit_app.py` saves PDFs/DOCX/TXT/MD to `documents/legal` or `documents/device`, lists files, and previews extracted text. It does NOT index uploaded documents.
- `mdr_rag/pipeline.py::run_index()` calls `mdr_rag/search.py::rebuild_index()`, writes `state/manifest.json`, and currently **prints** instead of returning a structured result.
- `mdr_rag/pipeline.py::check_manifest()` verifies file names, SHA-256 digests, and embedding model; it can raise if the index is missing or outdated.
- `rebuild_index()` currently deletes the existing Chroma collection before embedding all chunks. A failed rebuild may invalidate the previous index. Address this or clearly recover/report failure.

## Functional requirements
1. Add a visible **Index Documents** button within a Documents tab/section of the existing Streamlit app. Keep existing upload/save/preview functionality intact.
2. Index documents from BOTH `documents/legal` and `documents/device` using the existing embedding model, retrieval database, and indexer. Do not spawn a shell command; call a reusable Python service function.
3. After saving new/changed documents, show **Index out of date** until successful indexing. Do not claim the file is searchable immediately after upload.
4. On first launch, show `Not indexed` if no index exists. Show `Ready` only after checking the actual manifest and collection, not merely because `manifest.json` exists.
5. Display indexed file count, chunk count, last index time, embedding model, and warnings where available. If the index is stale, explain why and present the indexing button.
6. Show `st.spinner` while indexing; after success show `st.success` and updated counts; on failure show an understandable error and retry instructions. Avoid exposing full tracebacks to ordinary users, but log details for developers.
7. Disable indexing when no readable supported documents are present. Detect zero-readable-chunk uploads (scanned PDFs) and show a helpful OCR warning.
8. Prefer a minimal service such as `mdr_rag/app_services.py` exposing `index_documents() -> IndexResult` and `get_index_status() -> IndexStatus`, or equivalent typed structures.
9. Refactor `run_index()` into a reusable return-value function and thin CLI print wrapper, or introduce a shared service used by both CLI and Streamlit. **Keep `python main.py index` working.**
10. Account for Streamlit reruns: do not accidentally index on every rerun; only the button triggers indexing. Rerun the UI after a successful operation.
11. Preserve paths from `mdr_rag/core.py` (`DOCS`, `STATE`, `DBDIR`). Never use a different, silently divergent vector DB.
12. If improving failure resilience: stage/index into a temporary collection and switch only on success if compatible with current collection readers, or explicitly document and test the current rebuild's failure-retry semantics. Do not claim atomicity without implementing it.
13. Continue binding Streamlit to localhost in README; no public hosting or auth in scope.

## Suggested UI
```
Documents
  Upload [legal/device] [Choose files] [Save selected files]
  Legal: 2 files  |  Device: 1 file
  Index status: Out of date — 1 document added
  [Index Documents]
  Last indexed: ... | Files: ... | Chunks: ... | Model: ...
  Warnings: ...
  [Document selector] [Preview extracted text]
```

## Tests Codex must add
- Missing manifest -> Not indexed.
- Stale manifest after a new file, removed file, modified bytes, or changed model -> Out of date.
- Successful mocked index -> Ready, correct file/chunk metrics.
- Indexing failure -> visible actionable error; UI remains usable.
- Upload alone does NOT falsely mark the index Ready.
- CLI still runs indexing and writes compatible manifest.
- Empty/scanned PDF creates a clear unreadable-text warning.
- Rebuild cannot silently advertise a ready index when Chroma data is incomplete.

## Acceptance scenario
From an empty environment: start Streamlit; upload a short text-readable legal PDF; save; observe Out of date; click Index Documents; observe Ready, file count and positive chunk count; restart Streamlit; Ready remains; upload another file; observe Out of date; click Index Documents and return to Ready. No terminal indexing required.

## Deliverables
Implement code, update `README.md`, run targeted tests and `python -m pytest -q`, and summarize changed files, verified behavior, failures, and exact run commands. Do not start task 02 until task 01 passes its acceptance scenario.
