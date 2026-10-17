# Stage 07 — Requirement-level evidence assessment and citation auditing

## Goal
Replace loose passage summarization with traceable claims, abstentions and calibrated human review.

## Implementation
1. Evidence role B receives one active applicable requirement, verified legal source, bounded top device excerpts and profile context; emits schema `{status, claim_units:[{text,device_span_ids,legal_span_ids,verbatim_quotes}], missing_information, contradictions, explanation}`.
2. Enforce distinct source domains: requirement citation is legal; fulfillment evidence is device. Refuse unapproved/stale regulation, wrong project/source or unsupported pages. Whitespace-normalized literal quote must match retained source span; direct source IDs validated against snapshot.
3. Verifier pipeline: schema -> ID/page/offset/hash -> quotation containment -> semantic support for claims (human review or constrained optional verifier). A quote existing in a source does **not** prove the conclusion follows. Negative support and contradictory evidence should be surfaced.
4. Statuses: `supported`, `partially_supported`, `contradictory`, `not_found`, `unverifiable`; each explicitly refers to **document evidence**, not legal conformity. Keep `applicability` independent.
5. Recommendation role C or templates produce concrete actions **only** from verified findings, e.g. "locate risk-management evaluation" not "device violates Article X". Cite action's triggering finding; no fabricated tests or obligations.
6. Preserve failed/audited claims in internal state and show why they were rejected; only audited safe statements enter reports.

## Tests
- Fabricated source ID/page, legal quote used as device proof, partial quote out of context, word-negation inversion, contradictory documents, stale source hash, unsupported model generalization, requirement with no results, adversarial doc text instructing model to claim compliance.
- Property-based citation string fuzzing; tests for invalid JSON and retry cap; machine output never contains unreviewed "fully compliant" as finding.

## Fallback/gate
Missing/ambiguous evidence -> `not_found` or `unverifiable`, never `noncompliant`. Unsupported generated claim is suppressed; retain deterministic citations and request human review. 100% fabricated citation cases rejected in fixture tests.
