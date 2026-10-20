# VC implementation record

Implemented on branch `vc-implmentation`, 2026-10-20. This is the single record of
implemented changes, usage, schema, validation and limitations. Scope is
`01_DATA_FOUNDATION.md` is recorded first; Task 02 is recorded below. Tasks 03–05
are not implemented.

## Changes

| File | Implementation |
| --- | --- |
| `vc_engine/__init__.py` | Independent offline package; no MDR/model imports. |
| `vc_engine/models.py` | Exact three CSV header contracts, default paths, stable IDs, conservative whitespace/name/date/year/number/currency normalization, typed filters and company/document results. |
| `vc_engine/database.py` | SQLite schema version 1, application identity guard, foreign keys, indexes, deterministic upserts, separate read-only connections for queries. Rejects unrelated or unsupported databases. |
| `vc_engine/ingest.py` | UTF-8/BOM CSV preflight; strict headers; physical start/end lines; malformed-row/identity rejection; transactional accepted-row imports; preserved raw rows and per-field provenance; atomic JSON quality report. |
| `vc_engine/queries.py` | Company, investor, stage, company-country, clinical-category and literal keyword filters; document/fund search; pagination; source-history lookup; runtime counts and quality summaries. |
| `vc_engine/__main__.py` | `ingest`, `stats`, and `search` commands with JSON output, help and clear error exit codes. |
| `tests/test_vc_engine.py` | Synthetic fixtures covering idempotence, relationships, money separation, nulls, invalid inputs, provenance/history, offline queries, CLI, storage isolation and input counts before deduplication. |
| `data/vc/raw/.gitkeep` | Input-folder placeholder; no fabricated real CSVs. |
| `.gitignore` | Excludes local VC CSVs and downloaded/confidential source folders, including supplied `documents/vc/` inputs. Existing SQLite/sidecar/report ignore rules remain active. |
| `README.md` | Link to this implementation/usage record. |

No changes to `main.py`, `streamlit_app.py`, `mdr_rag/`, existing tests,
requirements, MDR state, source archives or Chroma collections. No new dependencies.

## Run locally

Copy the three CSVs named in `README.txt` into `data/vc/raw/`, then run from the
repository root (activate `.venv`, or use `.venv/Scripts/python.exe` on Windows):

```powershell
python -m vc_engine --help
python -m vc_engine ingest
python -m vc_engine ingest --companies path/to/companies.csv --investments path/to/investments.csv --documents path/to/documents.csv --db data/vc/medtech_vc.sqlite --report reports/vc_import_quality.json
python -m vc_engine ingest --companies documents/vc/europe_ai_samd_50_companies.csv --investments documents/vc/europe_healthtech_vc_50_investments.csv --documents documents/vc/vc_public_real_documents.csv
python -m vc_engine stats --db data/vc/medtech_vc.sqlite
python -m vc_engine search --query cardiology --db data/vc/medtech_vc.sqlite
python -m vc_engine search --country Germany --clinical-category Cardiology --investor "Fund A" --stage Seed
python -m vc_engine search --company "Heart AI" --limit 20 --offset 0
python -m vc_engine search --entity documents --query thesis --investor "Fund A"
```

Defaults resolve relative to the repository, not the shell's working directory.
Explicit paths resolve relative to the shell. `stats` and `search` open existing
databases read-only and do not initialize an empty database. CLI exit codes: 0
success; 1 import rejections or operational/validation errors; 2 argparse errors.
`ingest` preflights all three files before database writes; any file/header error
saves a failed report without importing any file. Valid rows are imported together;
bad row widths/missing identity fields are reported and rejected. Fix errors and
reimport. Reimport never deletes records absent from the new files.

Filters are case-insensitive exact matches except `--query`, a literal substring
across raw company/investment fields and investor names. Country means company
headquarters. All filters are combined with AND; investor and stage must match the
same investment. Results return every relationship for each matched company.
Document search accepts keyword and exact fund name (`--investor`) only. Pagination
uses `--limit` (1–10000) and `--offset`; default limit is 100.

Typed API for subsequent tasks:

```python
from contextlib import closing
from vc_engine.database import connect
from vc_engine.models import QueryFilters
from vc_engine.queries import search_companies, search_documents, provenance, stats

with closing(connect(readonly=True)) as connection:
    companies = search_companies(connection, QueryFilters(keyword="cardiology"))
    documents = search_documents(connection, keyword="thesis")
    quality = stats(connection)
    if companies:
        claims = provenance(connection, "companies", companies[0].id)
```

## Schema and normalization

SQLite defaults to `data/vc/medtech_vc.sqlite`. Application ID `1447250225` and
`user_version=1` protect against accidentally selecting an MDR/other database.
Tables:

| Table | Keys and principal fields |
| --- | --- |
| `companies` | Stable ID and unique casefolded name; headquarters, category, use case, founded year, cumulative funding amount/currency, revenue amount/currency/year, study URL, reported regulatory text, observation date, raw JSON. |
| `investors` | Stable ID and unique casefolded name; country, type, raw investor JSON. |
| `investments` | Stable ID; company/investor foreign keys; relationship, stage, round date, full round amount/currency, amount type, individual fund check amount/currency, reported verification text, observation date, raw JSON. |
| `source_documents` | Stable ID and unique casefolded input source ID; fund, title, type, year, format, source/landing URLs, reported verification text, observation date, raw JSON. |
| `source_rows` | Stable source row ID; dataset, full input path, filename, file SHA-256, physical start/end CSV lines, complete original row JSON. |
| `source_claims` | Composite key: entity table + entity ID + source row + input field. Stores original field string, whitespace-normalized string (null for blank), and independent verification flag fixed to 0. Join `source_rows` for filename/line/hash. |

Indexes cover company country/category, investment company, investment
investor/stage, investor country, document fund and entity provenance. Raw JSON keeps
every column, including URLs, notes, disclosure text, observation text and blanks.
Typed normalized numbers/dates live in the entity tables; claim normalization is
text-only. Investment rows contribute provenance to the relationship and its two
entities. Each input field, including blanks, has a provenance record. Source rows
with changed file bytes are retained separately, preserving earlier claims.

IDs use SHA-256 over normalized identity components. Company/investor identity is
name-based (NFC Unicode, collapsed whitespace, casefold); document identity uses
`source_id`. Investment identity includes investor, company, relationship, stage,
raw round date, announcement URL and portfolio URL. Amount and notes corrections
update the same relationship; different rounds stay separate. Unchanged file imports
do not duplicate entities, relationships, source rows or claims. Entity snapshots
use the last imported row; all conflicting input rows remain in provenance. An
investment-only company gets an unknown-fields placeholder, enriched by a subsequent
company import.

Numeric parsing accepts plain decimals or unambiguous comma thousands groups.
Ranges, scientific notation and approximate text stay raw/unknown. Blank is
null, while explicit zero remains zero. Company funding is converted from the
explicitly USD-millions column into USD units. Other amounts need a three-letter
currency alongside the number or the explicit round currency column. That column
also accepts explicit `USD million`, `EUR million`, or analogous three-letter
currency plus `thousand`/`million`/`billion` and scales into currency units. A fund check
does not inherit the round's currency; revenue does not inherit company country.
For example, `USD 500,000` is parseable; `$500,000`, `12 million`, and a bare revenue
`500000` are retained as raw text with unknown normalized amount. Dates require valid
`YYYY-MM-DD`; partial dates remain raw. No currency conversion occurs.

All regulatory/investment/document verification flags stay 0, regardless of
CSV-reported verification text. A source URL is preserved without fetching it.

## Import validation report

`reports/vc_import_quality.json` records input filenames/paths/hashes, input row
counts before deduplication, imported/rejected rows and reasons, blank counts per
field among accepted rows, fields left unparsed, per-table inserted/updated/unchanged
operation counts, final database counts, quality counts and provenance location.
Operation counts describe row-level upserts (including placeholder company and
investor operations); final counts describe unique stored entities. Counts are
computed at runtime. Row numbers refer to physical CSV lines, header at line 1;
multiline values retain both start and end line numbers. Fully empty lines are skipped.
Field-level audit data resides in SQLite rather than duplicating sensitive fields in
the report. Reports, inputs, local databases and confidential downloads are ignored.

## Validation and limitations

Commands run and results are recorded below before the implementation commit.

- `.venv/Scripts/python.exe -m pytest -q tests/test_vc_engine.py --basetemp reports/test-temp-vc-01`: initial 19 tests passed; pytest cache permission warning only.
- `.venv/Scripts/python.exe -m pytest -q tests/test_vc_engine.py -p no:cacheprovider --basetemp reports/test-temp-vc-02`: 21 passed after physical-line and pre-deduplication count cases were added.
- `.venv/Scripts/python.exe -m pytest -q tests/test_vc_engine.py -p no:cacheprovider --basetemp reports/test-temp-vc-final`: final 22 passed in 1.20 seconds, including transaction rollback and failed-database reporting.
- `.venv/Scripts/python.exe -m pytest -q tests/test_vc_engine.py -p no:cacheprovider --basetemp reports/test-temp-vc-real-units`: 22 passed in 1.53 seconds after adding explicit currency-unit handling for the real CSVs.
- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-vc-regression-01`: 575 passed, 2 skipped in 355.74 seconds. This run collected the original 19 VC tests alongside all existing repository tests; the final 22-test VC run above separately covers the later additions and final importer changes.
- `.venv/Scripts/python.exe -S -m vc_engine --help`: passed with site-packages disabled.
- Initial `.venv/Scripts/python.exe -S -m vc_engine ingest`: expected nonzero exit when files were absent from `data/vc/raw/`; saved a missing-input report. The real CSVs were subsequently found in `documents/vc/` during the final workspace check and successfully imported via explicit paths. The default quality report now contains successful real-data reimport results.
- `stats` and `search --query cardiology` against the final tiny synthetic fixture: passed; 1 company, 2 investors, 3 relationships, 1 document and all 254 field-provenance records preserved after reimport. Saved a separate successful synthetic report at `reports/vc_import_quality_synthetic.json`.
- `.venv/Scripts/python.exe -m compileall -q vc_engine`: passed.
- `git diff --cached --check`: passed. `git check-ignore` confirmed exclusion of local VC inputs, database, reports and downloaded/confidential documents.

The pre-existing untracked `docs/vc/README.txt` and task briefs are preserved and
excluded from the implementation commits; the new implementation log is committed.
Original CSVs in `documents/vc/` are preserved locally and ignored.

Real-data acceptance validation used the three supplied CSVs in `documents/vc/`,
with site-packages disabled (`python -S`), without network or Ollama:

- Exactly 50 company, 50 investment and 66 document input rows; all 166 imported,
  zero rejected. Initial unique inserts: 99 companies, 3 investors, 50 relationships,
  66 documents. Only one investment-company name matches the company catalog;
  49 investment-only companies get unknown-fields placeholders without fuzzy merges.
- Final unchanged reimport: zero inserted and zero updated entities/relationships;
  all entity, source-row and provenance counts unchanged. There are 166 source rows
  and 5,724 field provenance records.
- Six reported round amounts normalize with explicit USD/EUR million units;
  44 remain null. All 50 fund check amounts remain null. Revenue remains null for
  every company (including the 49 placeholders); none inherits cumulative funding.
- Quality summary: 99 unknown clinical-study URLs, 99 unknown revenue amounts,
  99 unverified regulatory statuses, 44 missing round amounts. This includes
  placeholders, so these counts intentionally differ from the company input count.
- `search_companies(..., QueryFilters(keyword='cardiology'))`: 3 results offline.
- One partial round date (`2021`) remains unparsed and preserved in provenance.
- `reports/vc_import_quality.json`: successful unchanged reimport report.
  `reports/vc_import_quality_normalized.json`: import after explicit-unit handling;
  `reports/vc_import_quality_initial.json`: initial import before that handling.

No source, funding, clinical evidence or regulatory claim has been independently
verified. No Ollama, network, scraping, credentials or cloud services are used.
Later tasks, dashboard, document extraction/indexing, enrichment, fuzzy entity
resolution and financial verification remain out of scope.

Name-only identity can merge distinct entities with identical names; the importer
does not infer subsidiaries/aliases. Investments with identical identity fields
are indistinguishable and deduplicate; changing round identity/source URLs creates
a different relationship. Schema snapshots are last-imported views, not conflict
resolution or bitemporal truth; retained provenance must be reviewed for conflicts.
All observations are unverified. SQLite and quality-report publication are separate
operations; an output error after commit does not undo the database transaction.

## Task 02 — FDA 510(k) regulatory precedent search

Implemented on `vc-implmentation`, 2026-10-20. Scope is
`02_FDA_REGULATORY_PRECEDENTS.md`. Tasks 03–05 remain out of scope.

### Changes

| File | Implementation |
| --- | --- |
| `vc_engine/regulatory_models.py` | Typed FDA queries, fetch limits, `RegulatoryPrecedent`/search results, literal query escaping, valid K-number checks, explicit scope and regulatory warnings. |
| `vc_engine/fda_client.py` | Opt-in `requests` transport to the fixed official HTTPS endpoint, timeouts, bounded retries/backoff/rate pacing, response-size cap, cache freshness and explicit live/cached page status. |
| `vc_engine/regulatory_store.py` | Dedicated versioned FDA SQLite cache, normalized records keyed by FDA K-number, complete raw API pages and query parameters, source URLs and fetch/check timestamps. |
| `vc_engine/regulatory_search.py` | Bounded pagination, deduplication/repeated-page detection, exact field checks, normalized optional fields, deterministic match reasons, live evidence flags and offline cached-record search. |
| `vc_engine/__main__.py` | Added `fda-search` and `fda-import`, explicit `--online`/`--refresh`, dedicated cache path and configurable request/pagination caps. |
| `tests/test_fda_regulatory.py` | 34 mock-only test cases covering success/no results, errors/timeouts/retries, missing/invalid IDs/fields, pagination/caps/duplicates, stale/fresh/offline caches, CLI and database isolation. Network is forbidden in these tests. |
| `requirements.txt` | Explicit `requests>=2.32,<3` dependency for live FDA operations; transport imports remain lazy. |
| `README.md` and this record | FDA entry points, scope, setup, exact commands, evidence status, validation and limitations. |

No modifications to Task 01 database schema, CSV ingestion/query code, MDR code,
Chroma indexing, legal/source archives, model settings or existing tests. The
existing SQLite/report Git ignore rules cover the new cache and demo artifacts.

### Setup and commands

Activate the existing project environment. For a fresh setup:

```powershell
python -m pip install -r requirements.txt
python -m vc_engine fda-search --help
python -m vc_engine fda-import --help
```

The environment already had `requests 2.34.2`; no installation was needed here.
Offline commands and Task 01 commands remain usable with `python -S`, without
site-packages, Ollama or credentials. No API key is embedded, loaded or required
by this client; it operates within the public unauthenticated API limits.

```powershell
# Offline by default: searches only previously captured FDA records.
python -m vc_engine fda-search --query echocardiography --limit 10
python -m vc_engine fda-import --k-number K251103

# Explicitly allow public API requests. Fresh cached pages are reused.
python -m vc_engine fda-search --query echocardiography --limit 10 --online

# Force a current official check and capture/cache the returned record.
python -m vc_engine fda-import --k-number K251103 --online --refresh

# Known structured fields are preferred over broad name matching.
python -m vc_engine fda-search --applicant "Philips Image Guided Therapy Corporation" --product-code OBJ --limit 1 --online
python -m vc_engine fda-search --device-name "ACUSON AcuNav Volume Intracardiac Echocardiography(ICE) Catheter" --limit 1 --online

# Separate FDA database and configurable bounds.
python -m vc_engine fda-search --query echocardiography --online --fda-db data/vc/fda_510k.sqlite --page-size 5 --max-pages 2 --max-records 10 --limit 10 --timeout 10 --retries 1 --cache-hours 24
```

For an existing company, inspect its local record using Task 01 `search --company`
and explicitly select an appropriate device-name phrase or known applicant/product
code for `fda-search`. Company names are not assumed to equal FDA applicants.
No CSV/company information is transmitted automatically.

Typed API:

```python
from vc_engine.regulatory_models import FDAQuery, FetchLimits
from vc_engine.regulatory_search import search_precedents

cached = search_precedents(FDAQuery(query="echocardiography"))
# Only this explicit online=True permits requests:
checked = search_precedents(FDAQuery(k_number="K251103"), online=True,
                           refresh=True, limit=1, limits=FetchLimits(retries=1))
```

### Cache schema, bounds and evidence semantics

Default FDA storage is `data/vc/fda_510k.sqlite`, separate from
`data/vc/medtech_vc.sqlite` and every MDR store. Application ID `1447249476` and
schema version 1 reject incompatible/VC/MDR databases. No implicit migrations of
other databases occur. Offline mode opens the cache read-only; an absent cache
returns `cache_miss` with zero requests and does not create a database.

- `fda_records`: K-number primary key; device name, applicant, decision date/code/
  description, product code, supplied medical specialty, complete original record
  JSON, actual fetched source URL, `fetched_at`, `checked_at`, retrieval status.
- `fda_pages`: deterministic hash of search/limit/skip/sort parameters; original
  complete API payload JSON, source URL, fetch timestamp and retrieval status.
  Upserts replace current snapshots without duplicating K-numbers or identical
  page keys. Raw pages preserve source detail that normalized fields omit.
- Missing/invalid optional fields stay null; unparseable dates remain in raw JSON.
  Missing or invalid FDA K-numbers are skipped with diagnostics, never synthesized.
  FDA decision descriptions/codes are retained literally, not converted into
  marketing or regulatory claims.
- `--query` is a literal phrase in `device_name`. Known name/applicant/K-number
  filters use `.exact`; product code uses its native three-letter field and an
  additional local equality check. All supplied filters are ANDed. Device-name
  text matching alone does not establish clinical relevance or AI/SaMD status.
- Default limits: 10 results, page size 10, at most 5 pages/100 received records,
  2 retries after the initial attempt, 15-second read timeout (connect at most 5
  seconds), 4 MiB per response, at least 0.3 seconds between request attempts, and
  24-hour fresh page reuse. The default request cap is 15 attempts per invocation.
  Hard configurable maxima: page size 1000, 25 pages, 1000 records/results,
  3 retries, 60-second read timeout. Streamed response size is bounded; requests
  timeouts are connect/read inactivity limits, not a process-kill wall-time limit.
- Only connection/timeouts and HTTP 429/500/502/503/504 retry. Numeric Retry-After
  waits up to 10 seconds are respected; larger/unparseable waits stop with a clear
  error instead of retrying early. Other HTTP/API failures surface their messages;
  errors do not silently become empty results or verified cache reads. A genuine
  `NOT_FOUND` 404 is a cached no-results response.
- `--refresh` requires `--online`. Fresh page reuse, offline snapshots and stale
  offline snapshots are all labeled cached and have
  `verified_by_official_record=false`. Last fetch/check timestamps remain visible;
  cached reads list no newly checked URLs. Offline matching uses a literal
  device-name substring and exact structured fields across the stored subset;
  it can differ from the API's phrase matching and is never an exhaustive search.
- Only records returned in a live HTTPS response, with a valid returned ID and
  matching supplied exact fields, get `verified_by_official_record=true` during
  that invocation. This means the administrative official record was fetched and
  checked, not that clinical equivalence, clearance strategy or compliance was
  established. `checked_official_urls` lists URLs actually checked on that run.
- Repeated pages, response/record/result caps and duplicates are explicit.
  Results deduplicate by returned K-number; pagination sorts by decision date.
  New upstream records/tied dates can affect paging; the tool does not claim a
  transactional snapshot of the live FDA database. A later-page failure may leave
  earlier successfully captured pages available for an explicit offline search.

### Validation results and checked official URLs

- `.venv/Scripts/python.exe -m pytest -q tests/test_fda_regulatory.py tests/test_vc_engine.py -p no:cacheprovider --basetemp reports/test-temp-vc-02-fda-initial`: 54 passed in 1.53 seconds.
- `.venv/Scripts/python.exe -m pytest -q tests/test_fda_regulatory.py tests/test_vc_engine.py -p no:cacheprovider --basetemp reports/test-temp-vc-02-fda-complete`: final 56 passed in 3.11 seconds (34 FDA and 22 Task 01 tests).
- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-vc-02-fda-regression`: 610 passed, 2 skipped in 279.30 seconds. This run collected the initial 32 FDA cases; the final focused run separately covers two added cases and the final FDA corrections.
- `.venv/Scripts/python.exe -m compileall -q vc_engine` and `python -S -m vc_engine --help`: passed.
- The initial sandboxed live call was blocked by connectivity restrictions. The
  same bounded public API demo succeeded with network permission. Live checks
  exposed two API differences from the first draft: sort must use a sortable
  field (`decision_date`, not analyzed `k_number`), and `product_code` has no
  usable `.exact` subfield. Both were corrected and tested against live records.

Successful live demo commands used `--timeout 10 --retries 0 --online --refresh`:

1. `fda-search --query echocardiography --limit 3 --page-size 3`: one request,
   3 records of 18 API-reported matches, explicitly truncated. Returned K-numbers:
   `K251103`, `K212959`, `K203726`. The devices are name matches (including
   intracardiac catheters); this is not evidence that they are AI/SaMD analogues.
   Checked at `2026-10-20T21:29:09.227666+00:00`:
   [official search response](https://api.fda.gov/device/510k.json?search=device_name%3A%22echocardiography%22&limit=3&skip=0&sort=decision_date%3Adesc).
2. `fda-import --k-number K251103`: live exact lookup confirmed the same returned
   ID. [Official exact-ID response](https://api.fda.gov/device/510k.json?search=k_number.exact%3A%22K251103%22&limit=1&skip=0&sort=decision_date%3Adesc).
3. Exact applicant + native product-code filter returned `K251103`:
   [official filtered response](https://api.fda.gov/device/510k.json?search=applicant.exact%3A%22Philips+Image+Guided+Therapy+Corporation%22+AND+product_code%3A%22OBJ%22&limit=1&skip=0&sort=decision_date%3Adesc).
4. Exact device-name filter returned `K212959`:
   [official exact-name response](https://api.fda.gov/device/510k.json?search=device_name.exact%3A%22ACUSON+AcuNav+Volume+Intracardiac+Echocardiography%5C%28ICE%5C%29+Catheter%22&limit=1&skip=0&sort=decision_date%3Adesc).
5. Offline API/CLI reads returned the three stored search matches with zero
   requests, empty newly checked URLs, cached status and all verification flags
   false. FDA K-number upserts reuse stored entities without touching Task 01.

Local ignored demo artifacts: `reports/fda_search_live_snapshot.json` (the saved
original live API page and fetch timestamp, not a new check),
`reports/fda_exact_import_live.json`, `reports/fda_exact_filters_live.json`,
`reports/fda_device_name_live.json`, and `reports/fda_search_offline.json`.

Official documentation inspected:
[overview](https://open.fda.gov/apis/device/510k/),
[fields](https://open.fda.gov/apis/device/510k/searchable-fields/),
[query syntax](https://open.fda.gov/apis/query-syntax/),
[pagination parameters](https://open.fda.gov/apis/query-parameters/), and
[usage limits](https://open.fda.gov/apis/authentication/).

### Regulatory limits

The MVP covers **510(k) administrative research precedents only**, excluding
De Novo and PMA. It is not a complete authorized-device inventory. 510(k)
clearance is not FDA approval; similarity is not substantial equivalence or a
legally valid predicate; US clearance does not establish EU CE marking.

No clinical intended-use comparison, pathway/classification/compliance judgment,
summary-PDF download, OCR, document indexing or semantic model ranking is performed.
The optional summary-download phase is deferred; results explicitly state that no
decision-summary/indications-for-use document has been retrieved or compared.
Only supplied/fetched fields support relevance reasons. Query text may be
sensitive; `--online` explicitly sends the provided search terms to the official
API. API and query snapshots are local and unencrypted; original MDR/VC workflows
are isolated and retain their previous evidence semantics.
