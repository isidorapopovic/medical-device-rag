# Codex Task 04 — VC investment comparables + controlled terminology

## Prerequisite
Task 01 (and Task 03 for integrated comparable company results). The user wants an editable venture-capital terminology file. Implement that as **human-editable `data/vc/vc_terms.yaml`** (or JSON if dependencies make YAML impractical), with a schema, seed entries, unit tests, and a lookup API. Do not bury glossary definitions in LLM prompts.

## Deliverable A — Terminology registry
Each term includes: `id`, `label`, `aliases`, `definition`, `category`, `formula` (if applicable), `unit`, `common_misinterpretations`, and `status` (`reviewed`/`draft`). Seed these entries:
- `pre_money_valuation`: company valuation immediately before new financing (exclude the new invested cash in simple priced-round models).
- `post_money_valuation`: pre-money valuation plus new financing in a simplified priced-round model; convertible securities/option-pool mechanics can complicate it.
- `funding_round_amount`: total capital raised in a specific financing round; NOT an individual investor's contribution.
- `investor_check_size`: amount contributed by an individual investor to a financing round; often not public.
- `total_funding_raised`: cumulative reported amount across company funding history, with source and as-of date.
- `ownership_percentage`: investor equity ownership (specify fully diluted vs issued shares and as-of date).
- `dilution`: reduction in percentage ownership following new equity issuance.
- `runway_months`: estimated cash remaining divided by net monthly cash burn, only if coherent inputs are available.
- `burn_rate`: cash outflow net of inflows per month (define gross vs net explicitly).
- `ARR`: annual recurring revenue from recurring contracts; not total annual revenue.
- `TAM`: total addressable market based on stated segment/geography/assumptions.
- `SAM`: serviceable available market within product/geographic scope.
- `SOM`: realistically obtainable share within a stated horizon.
- `MOIC`: investment proceeds/value divided by invested capital (gross vs net must be specified).
- `IRR`: annualized return considering cash-flow dates; not equivalent to MOIC.
- `TVPI`: (residual value + distributions) / paid-in capital at fund level.
- `DPI`: distributions / paid-in capital at fund level.
- `RVPI`: residual value / paid-in capital at fund level.
- `SAFE`, `convertible_note`, `liquidation_preference`, `pro_rata_rights`, `lead_investor`, `seed_round`, `series_a`, `cap_table`, `clinical_validation`, `regulatory_clearance`, `CE_marking`, `reimbursement`, `SaMD`.
Definitions are educational research glossary entries, not legal/accounting advice; warn against applying simplified formulas to real deal documents without expert review.

Implement: `python -m vc_engine terms list`, `python -m vc_engine terms show 'MOIC'`, and optionally `terms search 'revenue'`; case-insensitive alias resolution and clear unknown-term behavior. Add schema validator and document how users add or review terms. No hardcoded formulas producing metrics from missing data.

## Deliverable B — Investment comparables
Create query/report service for investor-company relationships from `europe_healthtech_vc_50_investments.csv`, joining to company profiles from `europe_ai_samd_50_companies.csv` by explicit normalized key with collision review rather than fuzzy auto-merges.
Return companies and investors matching specialty, indication, geography, stage, and product category (as available). Each result must show:
- investor and company, technology/use case, country, source URL, as-of date, relationship-verification note;
- round stage/date and **reported total round amount** only when present, currency, amount type;
- **individual fund check** only when separately reported;
- company **cumulative funding** only from company table with source/as-of and as a different column;
- missing-data and uncertainty notes.

Never infer investor check from round total. Do not assume a fund participated merely because it appears in a catalog of fund documents. Do not equate reported Dealroom funding with audited data. A catalog of links is not a verified document corpus.

## Deliverable C — VC documents catalog
Provide `vc-documents` CLI or query API for the 66 record link catalog. Display titles, source URLs, expected extractable fields, `verification_status`, and research priority. Fetching full documents should be a **separate explicit opt-in command**, not performed during basic CSV ingest; log download attempt, URL, HTTP status, checksum, observed date, and any extraction failures. Do not invent NAV, performance, fund returns, valuations, or check amounts when source docs have not actually been read.

## Acceptance tests
- Pre/post money glossary shows caveats; IRR and MOIC are not confused.
- Join handles mixed case/spacing and flags ambiguous company names.
- An undisclosed individual fund check remains NULL even when a round amount exists.
- A document catalog link without downloaded content does not create financial facts.
- Term schema validation fails cleanly on duplicate IDs/aliases and invalid formulas/units.
- Existing tests pass and example CLI output illustrates unknowns transparently.
