# Codex execution prompt — Stage 02: Document ingestion and provenance

Copy this entire file into Codex OR have a master prompt read this file directly from your project.

## Assignment
Implement **Stage 02: Document ingestion and provenance** for the existing `medical-device-rag` project. This is Product A (EU MDR regulatory evidence intelligence), explicitly NOT an IP/patent system. You are an implementation agent with permission to edit project files and run safe local tests. Read the full specification `stages/02_DOCUMENT_INGESTION_AND_PROVENANCE.md` and relevant `reference/ARCHITECTURE_AND_ACCEPTANCE.md` and `reference/TEST_MATRIX.md`. The stage specification is part of this assignment, not optional background.

## Stage-specific work
Add robust ingestion for PDF/DOCX/TXT/MD, physical page mapping, structural sections, source-span IDs, normalized text offsets, SHA256, duplicate/version behavior, parsing diagnostics and optional OCR behind a disabled feature flag. Preserve originals and document-type segregation.

## Expected stage gate
Cited snippets open exact source revision/page; duplicate, scan, malformed, page/table and prompt injection tests pass.

## Deliverables
Actual implementation code, meaningful automated tests with offline mocks and negative cases, accurate docs, migration or compatibility layer if needed, and progress report. Do not stop at a plan or skeletal methods. Implement every feasible point in the stage spec. Use realistic deterministic toy fixtures for tests, explicitly labeled as non-regulatory illustrations.

## Mandatory execution protocol
1. Treat this repository as an existing working project, not a greenfield rewrite. Read `AGENTS.md`, the actual repository structure, current README, relevant tests, and the referenced stage specification before editing. If filenames differ, resolve from inspected code; never invent existing modules.
2. Write a short stage execution plan and update `docs/implementation/PROGRESS.md` with status, inspected baseline, decisions, commands, test results, risk notes, and next action. Maintain `docs/implementation/DECISIONS.md` for material architectural tradeoffs. Make only the minimal scoped changes necessary.
3. Use Python type annotations and Pydantic where helpful; preserve existing CLI commands, local Ollama/BM25/Chroma support, current Streamlit features, and their output contracts unless a backward-compatible migration is implemented and tested.
4. Never fabricate MDR provisions, current law, device evidence, patent material, expert judgments, or evaluation ground truth. Toy fixtures must be labeled synthetic. No evidence means INSUFFICIENT_EVIDENCE, not NONCOMPLIANT. No output may declare legal certification or definitive conformity.
5. Keep external services optional. Tests must run offline with deterministic fakes/mocks. Do not download large models, call cloud APIs, scrape legal databases, transmit files, or install heavyweight libraries without first checking installed alternatives and recording an opt-in decision. Preserve privacy and local-first operation.
6. Set explicit bounded retries and timeouts for model/network IO; retry only transient failures and never schema/validation errors. Include per-run token/call budgets, circuit-breaker behavior and deterministic fallback. Log run IDs, stage, duration and error codes; do not log prompts, dossier contents, secrets or sensitive metadata.
7. Write tests before or alongside implementation: happy path, null/empty documents, wrong source, duplicate/versioned content, truncated outputs, invalid schema, missing model, timeouts, malicious instructions in documents, Windows paths, and failure recovery as applicable. Do not weaken or delete existing tests to pass the gate.
8. Run the smallest focused tests first, then `python -m pytest -q` and available lint/type checks. If required runtime services are unavailable, mark integration tests NOT RUN with a reason; deterministic offline suite still must pass. Include executable smoke-test commands and expected results.
9. Before marking the stage complete, check `git diff --check`, inspect the changes for secrets and unintentional edits, and update documentation. Return: summary, files changed, test commands with PASS/FAIL/NOT RUN, deviations, rollback, costs/latency considerations, unresolved risks.
10. If critical gates fail, investigate and fix within this stage; if they remain unresolved, mark BLOCKED and STOP rather than moving to the next stage. Never skip an incomplete stage silently. Do not commit, push, delete user files, deploy, or enable cloud transmission without explicit authorization.

## End-of-stage reporting
Update `docs/implementation/PROGRESS.md` with the stage's exact measured status. If PASS, state `STAGE_02=PASS`; if blocked, state `STAGE_02=BLOCKED` with a reproduction command. End the response with a brief gate verdict and the next stage filename. Do not start the next stage from this individual-stage prompt unless an overarching master prompt expressly instructs automatic progression.
