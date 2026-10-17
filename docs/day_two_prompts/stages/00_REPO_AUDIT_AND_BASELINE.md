# Stage 00 — Current-repository audit and compatibility baseline

## Goal
Understand live project and establish reproducible offline baseline before refactoring. **Do not migrate architecture yet.**

## Tasks
1. Inspect `README.md`, `main.py`, `streamlit_app.py`, `mdr_rag/**`, `eval/**`, `tests/**`, `.env.example`, requirements and `.gitignore`; list actual modules/functions/CLI flags. Treat `rag.py` as legacy, not the default app.
2. Map current flows (`inspect`, `locate`, `index`, `ask`, `extract`, `review`, `evaluate`, `graph`, Streamlit) and Chroma/BM25 states, paths, side effects, output contracts. Identify incompatible assumptions in this pack.
3. Run `python --version`, `python main.py --help`, `python -m pytest -q`; if absent configure pytest minimally. Run `python main.py inspect` only with available safe sample data; no model download automatically.
4. Create `docs/CURRENT_ARCHITECTURE.md`, `docs/BASELINE_AND_RISKS.md` containing command results, dependency versions, screenshots optional, actual gaps, data privacy audit, smoke-test matrix, reasoned preservation plan.
5. Add deterministic characterization tests for CLI argument parsing, file routing, retrieval config, citation formatting, original outputs, and safe no-Ollama failure; use tmp_path and fixtures. Never delete existing tests.
6. Identify generated files and sensitive data: gitignore database/vector stores, cache, secrets, source dossier contents, uploaded customer docs and runtime outputs without deleting user data.

## Tests / edge cases
- Empty legal/device directories; missing `.env`; Ollama not running; spaces/unicode in Windows paths; invalid CLI args; empty index; duplicate doc names; malformed JSON; imported legacy prototype not accidentally executed.
- Assert legacy commands expose same flags and formats unless documented migration shim.

## Gate
Deliver `docs/BASELINE_AND_RISKS.md` and compatibility tests. Mark actual failures. No broad refactor until resolved. Explain exact rollback and test commands.
