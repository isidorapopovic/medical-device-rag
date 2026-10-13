# Stage 0 baseline verification

Run ID: `stage0-20261013-89d8c02`. Verified on 2026-10-13 against checkout `89d8c02047743b35354c4006c5c5fa9c96b0b5b1` plus the Stage 0 working-tree changes. Implementation commit: see Git history for the Stage 0 commit on `qmatrix-impelmantion`.

Inspected `main.py`, retained legacy `rag.py`, every `mdr_rag` module, `.env.example`, `requirements.txt`, README and all existing tests. The modular Ollama path and requested example defaults already existed in this checkout. Clarified README configuration precedence, configurable retrieval, normalized quotation checks, evaluation differences, safe setup and destructive/output behavior. Added only shared positive-integer context validation at the two chat call sites; existing retrieval-mode and boolean validation remain in place. No later stage was implemented.

## Verification results

- System `python` resolves to Python 3.13 without `python-dotenv` or pytest: help and tests could not run with that interpreter. Used the existing `.venv/Scripts/python.exe` instead; README setup activates this environment.
- Before changes, the default pytest invocation produced 18 passes and 7 fixture setup errors: `PermissionError` accessing the sandbox-restricted Windows pytest temp directory. These were pre-existing environment errors, not assertion failures.
- Before changes, `.venv/Scripts/python.exe -m pytest -q --basetemp .pytest_stage0_before`: **25 passed**.
- After changes, `.venv/Scripts/python.exe -m pytest -q --basetemp reports/test-temp-stage0-after`: **31 passed** (25 existing tests and 6 new cases rejecting invalid context before Ollama chat). **No new regressions.**
- `.venv/Scripts/python.exe main.py --help`: passed before and after changes. It lists `inspect`, `index`, `extract`, `ask`, `review`, `evaluate`, `graph` and the diagnostic commands. No Gemini credentials or network inference are needed; chat/embedding calls are lazy.
- `git diff --check`: passed.

## Live baseline availability

Only mocked/API-free tests were possible for the requested review/retrieval baseline; **no real review or retrieval evaluation metrics were generated**. A read-only local Ollama model inventory succeeded. `embeddinggemma:latest` is present, but the requested/default `qwen3:4b` is absent. Other installed chat models were not substituted and no models were downloaded. There are two supported legal files and two supported device files, an existing manifest and a 15-requirement draft register. Their content was not printed. `eval/gold_queries.json` contains zero rows, so no valid human-labeled retrieval evaluation is available. Neither placeholder labels nor model-generated labels were used.

Missing run-ID support is not itself a blocker: an isolated Python wrapper can set `mdr_rag.pipeline.REPORTS = Path('reports/<unique-run-id>')` before `run_review(limit=2)`, while evaluation already accepts `--out`. Once the requested model and human-verified gold are available, use distinct report paths and validate the existing manifest/register alignment; do not rebuild the index to create a baseline.

## Preservation and limits

The user's `.env` was not opened or edited. Uploaded files, device profile, existing state, `vector_db`, and assessments were not modified. No index/reindex, extraction, real review, or legacy script was run. The legacy script shares the `vector_db` directory but uses a different Gemini-model-named collection; its missing `mdr_rag.tls` and `mdr_rag.quota` imports remain explicitly documented. Only dedicated test temporary outputs were generated. Mocked tests do not establish retrieval quality, regulatory accuracy, or performance guarantees.
