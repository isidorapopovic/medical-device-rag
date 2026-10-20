# Codex Task 03 — Startup profile + comparable device search + evidence gaps

## Prerequisites
Tasks 01 and 02. Reuse the project's existing document parsing, Ollama + Chroma embeddings, BM25 hybrid retrieval, and source anchoring as feasible. `rag.py` is a legacy prototype: extend the supported code in `mdr_rag/` or compose its public interfaces. Never break EU MDR workflows.

## Primary user journey
User enters startup profile as structured JSON or uploads a PDF/DOCX pitch deck; system extracts an editable profile, searches imported company records and FDA 510(k) results, ranks comparable devices/companies, then creates an **evidence-gap report**. A user must review/edit profile fields before relying on matches.

## Startup profile schema
Create typed model with `name`, `device_name`, `device_description`, `intended_use`, `clinical_indication`, `patient_population`, `input_modality` (CT/MRI/ultrasound/etc.), `target_user`, `workflow`, `technology`, `jurisdiction`, `claimed_regulatory_status`, `funding_stage`, `sources`, and `unknown_fields`. Missing values are NULL, not guessed. For fields extracted from a deck, capture page/chunk and exact short supporting quote. Do not treat pitch-deck claims as independent verification.

## Ranking pipeline
1. **Candidate generation**: query local FDA 510(k) cache + companies SQLite using exact fields, medical terms, and lexical search; optionally enhance with separate, namespaced Chroma vector collection and hybrid retrieval. Work in offline lexical mode without Ollama.
2. **Comparability filters**: same clinical purpose/intended use and patient population matter more than shared AI buzzwords. Record match/mismatch/unknown for intended use, modality, population, workflow, and regulatory classification.
3. **Transparent rerank**: configure weighted features, e.g. intended use 0.30, clinical indication 0.25, modality 0.20, population 0.15, workflow 0.10, but treat these as baseline tunable heuristics, not validated clinical equivalence. Missing/unknown dimensions should reduce coverage/confidence, not be forced into strong matches.
4. **Output**: top-k devices and companies with actual source IDs, source links, matched/mismatched fields, matched field evidence, uncertainty, and a rationale. Keep cleared devices distinct from merely competing companies; do not imply companies are FDA cleared because one product is.
5. **Evidence-gap extraction**: report absent or unverified clinical publications, external validation, prospective evidence, comparator studies, reimbursement evidence, regulatory documentation, and device-specific intended-use details. Use statuses `supported_by_source`, `claimed_only`, `not_found_in_index`, `conflicting`, and `needs_review`. `not_found_in_index` does **not** mean absent in the real world.

## Clinical publication extension (small and optional within this task)
Provide a `clinical_publications` table and an import mechanism for verified bibliographic records with fields `doi`, `pmid`, `title`, `year`, `study_design`, `population`, `endpoint`, `n_patients`, `performance_metric`, `performance_value`, `source_url`, `verification_status`. If live PubMed ingestion is implemented, document API, rate limits, retrieval timestamp, and deduplication by PMID/DOI. Do not claim study comparability from AUROC alone or directly compare metrics on different endpoints/populations.

## Suggested CLI / functions
- `python -m vc_engine profile --input path/to/startup.json --output reports/startup_profile.json`
- `python -m vc_engine compare --profile reports/startup_profile.json --top-k 5 --output reports/comparables.json`
- `python -m vc_engine evidence-gaps --profile ... --output reports/evidence_gaps.json`
Adjust names to the CLI established in Task 01; document final commands.

## Tests and acceptance
- Synthetic examples distinguish 'stroke CT triage' from 'cardiac ultrasound' despite both containing 'AI medical imaging'.
- No FDA candidate is returned as officially cleared unless its actual FDA record supports that claim.
- Missing FDA intended use cannot be reported as a confirmed match; score explainability includes match/mismatch/unknown.
- All evidence-gap statements have source status. A missing study URL must result in `not_found_in_index`/`needs_review`, **never** 'no clinical evidence exists'.
- Deck extraction is optional; structured input + CSV-only search run offline without Ollama.
- Golden labeled comparables (start with 10 human-annotated profiles) can be stored in `eval/vc_gold_comparables.json` and evaluated using Recall@5 and Precision@5; no fabricated gold labels.
- `python -m pytest -q` remains green.
