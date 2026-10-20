# Codex Task 01 — Build the MedTech VC data foundation

## Objective
Extend the existing `medical-device-rag` repository with a local, testable structured-data layer for companies, investment relationships, and public VC documents. **Do not replace or break the existing EU MDR RAG.** This task must run without Ollama and without network access.

## Repository context to inspect first
Read `README.md`, `main.py`, `streamlit_app.py`, `mdr_rag/`, `tests/`, `requirements.txt`, and `.gitignore` before editing. The supported application uses `main.py`, `streamlit_app.py`, `mdr_rag/`, Ollama, and Chroma; `rag.py` is an older unsupported prototype. Follow existing conventions. Keep VC data and existing MDR indexing in separate namespaces/storage. In particular, avoid clearing the MDR Chroma collection when indexing VC material.

## Input files
Expect the user to copy these files into `data/vc/raw/` (accept CLI paths as overrides):
- `europe_ai_samd_50_companies.csv` — 50 company rows.
- `europe_healthtech_vc_50_investments.csv` — 50 investor-company relationship rows.
- `vc_public_real_documents.csv` — 66 source catalog rows.

Actual headers (do not rename input columns or assume all are nonempty):
- Companies: `company`, `headquarters_country`, `selected_device_or_software`, `clinical_category`, `clinical_use_case`, `founded_year`, `dealroom_reported_total_funding_usd_millions`, `funding_source_url`, `revenue_value`, `revenue_year`, `operating_profit_or_loss`, `net_profit_or_loss`, `profitability_status`, `annual_financial_statement_url`, `regulatory_status_as_reported`, `regulatory_details`, `device_or_regulatory_evidence_url`, `ownership_as_of_2026_10_17`, `investment_diligence_priority`, `business_model_to_verify`, `clinical_evidence_study_url`, `risk_flags`, `research_date`, `data_quality_note`.
- Investments: `investor`, `investor_type`, `investor_country`, `company`, `product_or_platform`, `product_category`, `medical_device_or_samd_class`, `investment_relationship`, `reported_round_amount`, `reported_round_currency`, `amount_type`, `round_stage`, `round_date`, `individual_fund_check_amount`, `fund_check_disclosure`, `fund_portfolio_source`, `round_announcement_source`, `classification_source`, `fund_or_report_link`, `verification_level`, `diligence_notes`, `additional_market_report`, `as_of_date`, `regulatory_note`.
- Documents: `source_id`, `fund_name`, `document_title`, `document_type`, `year`, `format`, `direct_document_or_page_url`, `official_landing_page`, `relationship_to_listed_investor`, `expected_extractable_fields`, `verification_status`, `research_priority`, `important_notes`, `observed_2026_10_16`.

## Implementation
1. Create a `vc_engine/` Python package with `models.py`, `ingest.py`, `database.py`, and `queries.py` (or equivalent), following existing style.
2. Use SQLite as the source of truth, default `data/vc/medtech_vc.sqlite` (configurable). Model `companies`, `investors`, `investments`, `source_documents`, and a `source_claims`/`provenance` table if useful. Keep the **original raw values** alongside normalized fields for auditability.
3. Use stable IDs and deterministic upserts. Importing the CSVs twice must not duplicate data. Maintain investor-company many-to-many relationships; do not collapse multiple investments into one company field.
4. Normalize whitespace, names, optional dates, and numeric fields conservatively. Blank is **unknown/null**, not zero. Only interpret numeric values if parseable; preserve raw values. Currency must always be attached to amounts. Company cumulative funding, full round size, and individual fund check are distinct fields that must never be conflated.
5. For each imported field/claim maintain its input filename and row number; preserve source URLs, verification text, date observed, and notes. A URL alone does not mean the source was independently checked. Do not label any data verified simply because the CSV says it is.
6. Implement CLI entry points that do not disrupt `main.py`: `python -m vc_engine ingest --companies ... --investments ... --documents ... --db ...`, `python -m vc_engine stats --db ...`, `python -m vc_engine search --query 'cardiology' --db ...`. Add help text and examples in a small VC README or section of root README.
7. Add basic filters: country, clinical category, company, investor, stage, and keyword. Provide a typed query API for subsequent tasks.
8. Add indexes and record-count/data-quality summaries: unknown clinical-study URL, unknown revenue, unverified regulatory status, missing investment round amount. Print counts derived at runtime, not fixed expectations.
9. Preserve the repository's local-first posture. No external requests, scraping, credentials, or cloud upload in this task. Exclude downloaded confidential decks and local DB from Git unless intentional.

## Deliverables
- Import and query modules, CLI, documented database schema, tests with tiny synthetic fixtures.
- An import validation report with rows read/imported/rejected, errors, missing values, and field provenance. Save e.g. `reports/vc_import_quality.json`.

## Acceptance tests
- `python -m pytest -q` still passes for existing tests.
- On the supplied CSVs, import reports exactly 50 company input rows, 50 investment input rows, and 66 document catalog input rows **before** any deduplication; record actual inserted/upserted totals separately.
- Reimporting unchanged files results in zero duplicated entities/relationships.
- Missing revenue and round amount remain NULL; USD company total funding is not incorrectly treated as an investor check.
- Search works without Ollama/network. Invalid CSV columns yield clear errors rather than silent data corruption.

## Codex working rules
First inspect actual interfaces. Implement in small steps, run tests, list edited files, commands run, and remaining limitations. Do not fabricate evidence or claim funding/clinical/regulatory verification that was not performed.
