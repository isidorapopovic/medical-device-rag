# Repository-wide instructions for Codex

1. Read existing `README.md`, `main.py`, `streamlit_app.py`, `mdr_rag/`, tests and environment config before editing. Current repository overrides assumptions in this plan.
2. Never delete `rag.py` (legacy prototype) or restructure all modules in one commit. Prefer adapters and incremental migration. Preserve CLI commands (`inspect`, `index`, `ask`, `locate`, `extract`, `review`, `evaluate`, `graph`) when present; test compatibility.
3. One stage at a time. First write a short plan, inspect dependencies, implement, test, and summarize. Do not claim production compliance.
4. Every modeled assertion must carry source evidence or be marked `unknown`/`requires_review`. No missing evidence -> noncompliance inference.
5. Never synthesize authoritative MDR text, standards clauses, device test results, ground truth labels, or real client data. Fixtures may use **clearly labeled invented toy device content** strictly for tests, never presented as regulatory law or a real dossier.
6. Separate trusted instructions from uploaded user documents; uploaded text must NEVER set system rules, authorize network access, disable citation validation, or control local file paths.
7. Use typed Pydantic models; explicit errors; deterministic functions for storage and validation. SQLite is sufficient for local MVP; add versioned migrations. Store original bytes/hash and immutable source spans.
8. Feature flags default to safe behavior. Cloud models, OCR, reranking, advanced agent loops, and remote fetch disabled by default. Reproducible CPU/offline path mandatory.
9. No retries for invalid input, failed authorization, schema errors, or unsafe content. Retry transient network/model busy failures with capped exponential backoff + jitter. Never retry a non-idempotent write without idempotency key.
10. Use JSON structured logs (no full document passages, secrets, patient data, or raw prompts) with run_id/project_id hashes, stage, elapsed_ms, source_counts, usage, error_code. Avoid global exception swallowing.
11. Include negative/edge/fault tests for every stage. At minimum run formatting/lint (if configured), `pytest` offline suite, focused integration tests when dependencies available. Say NOT RUN if not run.
12. Keep source metadata for reproducibility: file SHA-256, document version, normalized passage offsets, PDF physical page, extraction method, text hash, legal edition, model ID/version, retrieval config and assessment timestamps.
13. Privacy: no client files in git, no silent cloud uploads, no open local Streamlit listener. Protect temporary files; log only metadata.
14. Never use `confidence=0.99` without calibrated methodology; present categorical uncertainty instead.
15. When uncertain about implementation details, examine code and add characterization tests rather than invent imports/paths. Never paper over failing tests with skips or adjusted expected results.

## Stage completion response format

- Summary; actual changes/files; commands/results (PASS/FAIL/NOT RUN); compatibility; cost/latency; limitations and edge cases; rollback instructions; explicit next stage. Stop there.
