# Stage 04 — Verified regulatory requirement registry

## Goal
Move away from treating LLM-extracted requirements as authoritative or exhaustive.

## Implementation
1. Build persistent `RegulationEdition` and `Requirement` tables plus import/export JSON schema and explicit review/activation lifecycle: `proposed -> source_verified -> specialist_reviewed -> active`, with rejection/retirement. `requirements_draft.json` import remains **draft**.
2. Retain exact legal source edition, official URL, downloaded file hash, jurisdiction, page/span ID, section/article/annex path, effective/as-of date metadata where verified. Distinguish original vs consolidated text and official legal provisions vs nonbinding guidance. Never assume upload is latest law. No copyrighted standards text redistribution without rights.
3. Add offline requirement import from explicitly supplied legal documents; prompt-assisted extraction can propose only; deterministic quote+span matching; reviewer must approve every item for activation. Also supply no-law fallback: block applicability analysis with `legal_registry_not_ready`.
4. Provide registry coverage report: which Annex/article sections are loaded, which are missing, draft vs active counts, validation as-of date, amendment/currentness warning; compare expected coverage to a manually verified coverage manifest, not to the model's own list.
5. Expose requirement dependencies and evidence-type tags, but no synthetic legal obligation text. Never auto-label standards harmonized or mandatory merely because mentioned.

## Tests
- Same section IDs in different editions; conflicting amendments, invalid effective date, forged legal snippet, incorrect page; withdrawn requirement, duplicated clause, stale legal edition; no source URL, no uploaded law, draft requirements mistakenly selected, partial Annex I.
- Import/export roundtrip with hashes; test that inactive requirements cannot enter final report.

## Gate
All active requirements trace to approved exact legal spans and edition. Reports clearly say `partial registry coverage` whenever incomplete. Human-curated seed dataset may start with a **small explicitly selected verified** group, never auto-filled fake laws.
