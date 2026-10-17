# Stage 10 — Local Streamlit reviewer workspace + report export

## Goal
Extend current upload/preview UI without starting a costly frontend rewrite.

## Pages
Project selection; documents (legal vs device + extraction warnings); device profile with citations/edit history; registry edition/coverage; applicability grid; evidence assessment with legal/device side-by-side excerpts; review queue; gap action plan; run cost diagnostics; report/export.

## Implementation
1. Reuse present Streamlit upload code but call services, not duplicated business logic. Project isolation and safe session IDs. Distinguish file parsing from index progress and assessment readiness.
2. Clearly label machine findings `draft - not a legal determination`; show legal edition and source-as-of status; show partial registry coverage and skipped/unreadable pages prominently; never present a percentage of legal compliance.
3. Review controls accept/override/reject + reviewer, timestamp, reason; override requires reason and cannot silently change original text. View citation opens verified source with correct physical PDF page or DOCX block.
4. Produce JSON + Markdown initially; add DOCX/PDF export only if warranted and templates tested. Include exact sources, edition, model config, timestamps, human decisions, unresolveds, sections skipped, assessment limitations. Sanitized export filenames; no original private content beyond user-selected report data.
5. Provide simple demo using clearly labeled fictitious device document and a user-uploaded verified legal source; no implicit real-world compliance score.

## Tests
- 0 docs, unreadable source, unknown classification, invalid source links, stale report, refresh midway, same filename/version, huge report, malicious markdown injection, rerun button double click, no Ollama, no active verified registry. UI smoke via Streamlit AppTest if feasible; service tests mandatory.

## Gate
Local complete flow from upload -> profile correction -> evidence review -> export works; machine/confirmed decisions visually distinguishable; report includes valid citations and incomplete-coverage warning.
