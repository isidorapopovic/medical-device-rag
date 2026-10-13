# Stage 6 verification

Verified on 2026-10-13 on `qmatrix-impelmantion`, based on Stage 5 commit `1ad39e3403a371340b025595ffa1ad927008998c`. Implementation commit: see Git history for "Stage 6: Add structured claim review and deterministic citation auditing".

## Implemented behavior

- Draft generation returns a strict structured claim inventory and obligation coverage. Every substantive assessment, factual reason, missing-information assertion, proposed action and applicability assertion originates in an inventoried claim. Uninventoried narrative is rejected; coverage explanations in exports are deterministic references to claim IDs rather than free model prose.
- A separate local model call reviews every claim ID exactly once using `supported`, `contradicted` or `insufficient`, with cited reasons and per-obligation coverage. Missing, duplicate and invented IDs fail validation. Instructions cover negation, modality, exceptions, scope, contradictions and overstated completeness. Unverified applicability cannot be promoted through a reviewer assertion.
- Shared `CitationAuditor` checks immutable buffer/chunk identities, legal/device roles, hashes, raw span offsets, locators and selected context membership. Both draft and reviewer quotes are checked. Device facts cannot rely on legal text alone; legal duties require legal basis; mixed/applicability assertions require both roles. Real quotes can still fail semantic policy. A complete status also requires coverage of every registered atomic obligation and explicit qualifier, linked to relevant cited claim IDs.
- One repair attempt is allowed per section draft cycle when verified legal and device context exists. Its budget is persisted before inference. Repaired claims are audited again against the same source context, with a separate generation binding. Interrupted repair cannot gain a second attempt. Unresolved validation becomes an explicit `needs_review` section without rejected factual narrative or citations. Initial draft/model/schema errors remain explicit failed executions. Exception text containing private excerpts is not persisted.
- Claim revision and context bindings include the whole draft, requirement/applicability inputs, source snapshots/ranges, generation call, reviewer model/context and validation policy. A `validation` checkpoint preserves completed work. State loading rejects semantic publications without a separate completed reviewer call and a matching passing inventory/context, or with edited publication fields/citation links. Supported/partial requirement findings require a verified device fact, not recommendations alone. Reviewer prompt/schema/policy changes invalidate validation; targeted updates preserve unaffected findings and traces.
- State schema 3 reads schemas 1/2 without rewriting archived snapshots or inventing semantic audits. Historical raw-only and legacy findings retain their limitations. Canonical state/history preserve rejected drafts and complete reviews for internal audit. Compatibility JSON/Markdown expose validation summaries, not rejected drafts or raw reviewer output.
- `run_ask` uses the shared claim auditor and semantic policy. Answer text comes from the generation-time inventory; omitted audits, quote/role failures, semantic rejection and reviewer errors abstain. It conservatively requires a supporting span for every claim, retains the previous 12-character minimum for both draft and reviewer quotes, and has no repair loop. Legacy normalized extraction validation remains unchanged.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage6-before -p no:cacheprovider
# Baseline: 215 passed, 1 skipped in 104.17 seconds; no pre-existing failures.
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage6-full -p no:cacheprovider --tb=short
# First complete implementation: 253 passed, 1 skipped in 181.17 seconds.
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage6-release -p no:cacheprovider --tb=short
# Final: 257 passed, 1 skipped in 207.28 seconds.
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Help, dependency consistency and whitespace checks passed. The 42 new deterministic cases cover absent/omitted/duplicate/invented audits; fabricated and genuine-but-irrelevant quotes; negation reversal; contradictory device passages; wrong corpus roles; missing legal qualifiers and overstated coverage; unsupported applicability; actual source-text prompt injection; successful repair; timeouts/invalid schemas; interrupted review and repair; targeted updates; tampered saved bindings/publication fields; recommendation-only partial findings; and shared `ask` abstention, including short quotes. Existing fixtures now return the structured drafting/reviewer schemas. Assertions were updated where unresolved coverage is withheld as `needs_review` rather than published as a partial self-assessment. Intermediate failures identified JSON-escaped versus literal raw-context tracing and normalization of published quote offsets; both were corrected without weakening raw-span validation.

All Stage 6 model/retrieval responses were mocked against synthetic passages. These tests establish procedural behavior, not semantic accuracy, legal sufficiency or resistance to every injection. The same local generation model may make correlated errors in a reviewer call; real semantic evaluation requires independent human labels. No real-corpus assessment, model download or cloud inference was performed. The opt-in real cross-encoder test remains skipped. The user's `.env`, documents, register, existing index and existing reports were not modified; synthetic outputs are beneath ignored `reports/test-temp-stage6-*` directories.
