# Codex Task 02 — Add FDA device records and regulatory precedent search

## Prerequisite
Complete `01_DATA_FOUNDATION.md`. Read actual repository code; reuse local indexing/retrieval helpers where appropriate, but **do not mix FDA records into the existing MDR legal corpus or silently alter MDR analysis**.

## User story
For a new AI/SaMD startup (or an existing company in the VC database), identify potentially relevant FDA 510(k) decisions and explain how closely they relate to its clinical intended use. Search results are **research precedents, not determinations of a legally valid predicate or clearance strategy**.

## Data sources
- Official openFDA device 510(k) API: `https://open.fda.gov/apis/device/510k/` and endpoint `https://api.fda.gov/device/510k.json`.
- Official FDA 510(k) decision summaries (if linkable and retrievable) as separately captured documents; use primary FDA source URL.
- Do **not** assume a list of 510(k) records is an exhaustive list of all authorized devices: other pathways include De Novo and PMA. The MVP covers **510(k)** and must label that scope.
- Network requests must be opt-in/explicit, bounded, cached, and skipped in unit tests.

## Implementation
1. Create `vc_engine/fda_client.py`, `regulatory_models.py`, and `regulatory_search.py` (or similar). Use `requests` with timeouts, retries/backoff for transient errors, API error messages, and configurable pagination/caps. Do not hardcode API keys. Respect usage limits; add user-agent if appropriate.
2. Implement search by `device_name`, applicant/manufacturer, and, if supported/available, product code; prefer exact filtering when fields are known. Do not assume `device_name` semantic matching is sufficient.
3. Store minimally: `k_number`, name, applicant, decision date, decision description, product code, medical specialty where supplied, raw FDA response, source URL, date fetched, and retrieval status. Preserve missing values, uncertainties, and distinction between `decision` and marketing claims.
4. Expose `python -m vc_engine fda-search --query 'echocardiography' --limit 10` and a cached `fda-import --k-number K...` workflow (choose actual CLI design after seeing Task 01).
5. Create `RegulatoryPrecedent` results with `relevance_reasons`, `limitations`, `evidence_urls`, and `verified_by_official_record` only when the live official record was actually fetched and checked; otherwise label `unverified`/`cached` with fetch timestamps.
6. Optional phase: download publicly available FDA 510(k) summaries into a separate file store, capture URL, access timestamp, checksum, and page provenance. Do not invent a summary if unavailable, do not OCR by default, and keep this separate from MDR legal documents.
7. Add a short regulatory warning: 510(k) clearance is not FDA approval, similarity is not proof of substantial equivalence, and US clearance does not imply EU CE marking. Avoid final pathway, classification, or compliance judgments.

## Example response structure
```json
{
  "query": "AI echocardiography analysis",
  "scope": "FDA 510(k) research precedents only",
  "results": [
    {
      "k_number": "EXAMPLE_ONLY",
      "device_name": "Example device",
      "source_url": null,
      "source_checked_at": null,
      "match_rationale": "Same imaging modality; intended use not yet compared",
      "limitations": ["Not a predicate determination"],
      "evidence_status": "unverified_example"
    }
  ]
}
```

## Testing and done criteria
- Mock FDA API responses: success, no results, HTTP errors, timeout, missing fields, repeated pages, duplicate `k_number`, and offline cached mode.
- Queries never return invented FDA clearance IDs. Each returned `k_number` must come from stored/fetched FDA data.
- Data persistence is idempotent and separate from VC CSV ingest and MDR RAG indexing.
- Demonstrate a query and list checked official URLs and limitations; if offline, show cached/unverified status prominently.
- Existing test suite remains passing; document exact setup and run commands.
