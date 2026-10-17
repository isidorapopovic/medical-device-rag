# Stage 05 — Applicability and classification analysis

## Goal
For each active requirement, decide candidate applicability separately from evidence sufficiency; preserve uncertainty.

## Implementation
1. Rules DSL or pure Python predicates for verified requirement conditions; rules use profile fields with tri-state logic (`true|false|unknown`) and explain each predicate. Never infer `false` from absent profile data.
2. Classification/qualification: generate **candidate** reasoning grounded in specific legal citations and known device attributes; force specialist review for high-impact or conflicting facts. Do not claim certified class or CE pathway.
3. Return one of `applicable`, `not_applicable`, `conditional`, `unknown`, `requires_human_review`; each stores cited legal source, device attribute sources and explanation. Rule precedence and edition scoping explicit; human overrides versioned.
4. LLM role A may explain ambiguous cases using bounded passages but may not override failed rule checks. If required attribute unknown, generate targeted question to human.
5. Optimize zero model calls for deterministic applicable/not-applicable predicates, use cached evaluation keyed to profile+requirement edition hashes.

## Tests
- Unknown vs false on invasive/sterile; conflicting patient population; multi-purpose products; irrelevant guidance; rule exception; different editions; changes to profile invalidate affected results; manually set `not_applicable` requires reason/reviewer.
- Metamorphic: irrelevant product-name edits do not change classification; changing a rule-relevant attribute triggers reevaluation.

## Gate
No `not_applicable` without a valid exclusion rationale and sources. Unknown stays unknown. All candidate classification results labeled for review.
