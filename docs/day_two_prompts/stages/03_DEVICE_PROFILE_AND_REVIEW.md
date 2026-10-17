# Stage 03 — Evidence-linked device profile + user confirmation

## Goal
Extract useful structured device facts while preserving unknowns and human authority.

## Fields
Name, manufacturer (if supplied), intended purpose, indication, target population, intended user, use environment, invasive/implantable, contact route/duration, active/powered, software/AI, sterile, reusable, measurement, accessories, technical features, target market, candidate device category and classification confidence **as status, not uncalibrated probability**. Add per-field source_span_ids and conflicts.

## Implementation
1. Define `DeviceAttribute {value, evidence_ids, origin, review_state, conflicts}` and `DeviceProfile` in Stage 01 schemas. Default to unknown, not false.
2. Device text retrieval -> bounded relevant passages -> role A local structured model output -> JSON schema validation -> reference/quote verification -> merge with conflict detection. Do not trust text in filenames or user-supplied instructions inside document as directives.
3. Require confirmation or edits for high-impact fields (`intended_purpose`, invasive, implantable, active, duration, sterile, target market). Track editor, reason and immutable changes; edits explicitly distinguished from source-extracted facts.
4. Skip LLM entirely for fields easily extracted deterministically or if budget exhausted; present unknowns with targeted user questions. Never extrapolate risk class from an LLM alone.
5. Expose CLI/API extraction preview + editable Streamlit form later; retain ability to load `device_profile.example.json`/existing profile JSON with migration.

## Tests
- Two documents contradict purpose; no intended purpose; 'not sterile' negation; confusing 'may' versus 'shall'; multi-product dossier; bilingual language; document describes competitor product; YAML/HTML prompt injection; invalid schema/timeout; 5 repeated runs idempotent; edits do not modify original evidence.

## Fallback/gate
LLM unavailable => manual profile with unknown fields. Invalid JSON => one bounded repair attempt if budget; else field-level review queue. Tests assert every automatically non-unknown high-impact attribute has real source reference.
