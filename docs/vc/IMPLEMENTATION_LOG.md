# Task 01 implementation record

Implemented on branch `vc-implmentation`, 2026-10-20. This is the single record of
implemented changes, usage, schema, validation and limitations. Scope is
`01_DATA_FOUNDATION.md`; tasks 02–05 are not implemented.

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
| `.gitignore` | Excludes local VC CSVs and downloaded/confidential source folders. Existing SQLite/sidecar/report ignore rules remain active. |
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
Ranges, scientific notation, units and approximate text stay raw/unknown. Blank is
null, while explicit zero remains zero. Company funding is converted from the
explicitly USD-millions column into USD units. Other amounts need a three-letter
currency alongside the number or the explicit round currency column. A fund check
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
- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp reports/test-temp-vc-regression-01`: 575 passed, 2 skipped in 355.74 seconds. This run collected the original 19 VC tests alongside all existing repository tests; the final 22-test VC run above separately covers the later additions and final importer changes.
- `.venv/Scripts/python.exe -S -m vc_engine --help`: passed with site-packages disabled.
- `.venv/Scripts/python.exe -S -m vc_engine ingest`: expected nonzero exit because all three real CSVs are absent; saved `reports/vc_import_quality.json` with `failed_preflight`, missing-file errors and zero rows read. No real VC database created.
- `stats` and `search --query cardiology` against the final tiny synthetic fixture: passed; 1 company, 2 investors, 3 relationships, 1 document and all 254 field-provenance records preserved after reimport. Saved a separate successful synthetic report at `reports/vc_import_quality_synthetic.json`.
- `.venv/Scripts/python.exe -m compileall -q vc_engine`: passed.
- `git diff --cached --check`: passed. `git check-ignore` confirmed exclusion of local VC inputs, database, reports and downloaded/confidential documents.

The pre-existing untracked `docs/vc/README.txt` and task briefs are preserved and
excluded from the implementation commit; the new implementation log is committed.

The supplied real-data acceptance check (50 company, 50 investment and 66 document
input rows) remains pending those CSVs. A synthetic 50/50/66 fixture tests counting
before deduplication; it does not stand in for validation of the real inputs.
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
