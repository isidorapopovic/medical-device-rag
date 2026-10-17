# Stage 12 — Final system review, demo and deployment decision

## Goal
Prove Product A works end-to-end and identify claims that remain unvalidated.

## Tasks
1. Re-run Stage 00 commands; verify no unexpected breaking changes. Run full lint, tests, migrations, offline evaluation and optional labeled-model benchmark; capture exact versions/date.
2. Manual demo with a clearly fictitious toy device and a verified uploaded legal subset (do **not** present toy regulation as real MDR): create project, upload, inspect extraction warnings, edit profile, approve/activate a real sourced clause in demo dataset, determine applicability, retrieve device evidence, audit citations, reject a false claim, review a partial finding, export and re-import report.
3. Failure demo: no Ollama; unknown intended purpose; unapproved legal registry; wrong citation ID; contradictory device documents; model budget exhausted; stale edited document; forced restart; rerun with same snapshot; malicious uploaded instructions. Verify safe degradation.
4. Produce `docs/PRODUCT_A_RELEASE_REVIEW.md`: scope, architecture, data provenance, test results, metrics (N and confidence intervals), failure rates, known gaps, cost/performance on CPU, screenshots if available, security status, regulatory specialist validation gaps.
5. Make go/no-go decisions: local demo allowed after deterministic checks; limited private pilot only after expert evaluation and privacy review; public launch requires authentication, tenant isolation, security review, legal-content maintenance and documented governance.

## Final gate
No invented legal claims or accuracy numbers; report always says assessment is document-evidence mapping, not approval; every key claim has valid citation or unresolved label; all critical flaws recorded and release blocked if unresolved.
