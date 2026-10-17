# Copy this entire prompt into Codex from the existing repository root

You are a senior Python developer and reliability-oriented AI engineer. Our target is Product A: EU MDR regulatory *document-evidence gap assessment* only. Read `AGENTS.md`, `README.md`, `reference/ARCHITECTURE_AND_ACCEPTANCE.md`, and `stages/00_REPO_AUDIT_AND_BASELINE.md`. Inspect the repository before modifying anything. Execute **only Stage 00** now. Preserve `main.py`, `streamlit_app.py`, the supported `mdr_rag` implementation and existing tests. Treat `rag.py` as legacy. Implement characterization tests and baseline documents. Never fabricate legal text, citations, results or completed tests. Run offline tests, give exact commands/results and compatibility notes, then STOP. Wait for my next stage instruction.

For subsequent stages say: `Execute stages/01_FOUNDATIONS_AND_CONTRACTS.md, following AGENTS.md. Stop after tests and report.` (replace file name per stage).
