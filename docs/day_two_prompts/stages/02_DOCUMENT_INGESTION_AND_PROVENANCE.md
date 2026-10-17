# Stage 02 — Document processing, ingestion and source provenance

## Goal
Original-file-backed citations across PDF/DOCX/TXT/Markdown, with reliable extraction warnings.

## Implementation
1. Reuse existing loaders; introduce isolated parsers and content-addressed original storage per project; UUID/version + SHA256 + mime sniffing. Never trust uploaded filename for path; sanitize traversal and reserved Windows names; atomic writes and temp cleanup.
2. PDF: preserve 1-based physical page and page text; DOCX: preserve paragraph and table indices; TXT/MD: block and line offsets; normalize whitespace *once*, record exact normalization version, source char offsets/hash. Create `SourceSpan` records with deterministic IDs per document version+location+text hash.
3. Add extraction-quality warnings for empty/scanned pages, missing tables, unexpected encodings, password-protected PDFs and damaged files. Optional OCR behind config; if not installed mark `needs_ocr`, not blank/success; OCR-derived text visibly tagged and cannot silently become verified legal source.
4. Maintain separate `legal`/`device` logical collections and immutable originals. Support re-upload same bytes as idempotent; different bytes same name create a new version, not overwrite. Re-index only changed docs where feasible; never mix project/collection indexes.
5. Expose extraction manifest and idempotent CLI/service functions. Track document status: `uploaded`, `parsed`, `partial`, `failed`, `needs_ocr`. Allow view of source excerpt plus surrounding context.

## Tests
- Empty 0-page/blank PDFs, encrypted/corrupt PDF, poor OCR, tables, rotated pages, unicode Serbian Latin/Cyrillic, superscripts, quote whitespace normalization, 51 MiB upload, zip bomb-like file, MIME mismatch, DOCX without page numbers, duplicate filenames, identical SHA across projects, delete/reupload, interrupted atomic write.
- Path traversal `../../secrets`, symlink outside allowed root, embedded prompt injection text must remain inert data.
- Fixture PDFs/DOCX may be generated within tests; label as toy, not official regulation. Verify 1-based citation pages and hashes.

## Fallbacks / gate
PDF page with extraction failure -> `partial/needs_ocr`; no source-based answer from unreadable page. Roll back metadata if original file write fails. Tests show no cross-project leakage or silent empty legal indexing. Legacy `index` still works.
