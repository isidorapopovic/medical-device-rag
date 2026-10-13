# Stage 2 verification

Verified on 2026-10-13 in the working tree on `qmatrix-impelmantion`, based on Stage 1 commit `75c1e0dc4df5cd9d7c9a32923306e1df1983ffe5`. Implementation commit: see Git history for "Add immutable source snapshots and raw-span evidence provenance" on `qmatrix-impelmantion`.

## Implemented behavior

- `source_buffer.py` provides immutable content-addressed `SourcePassage` snapshots and the requested `add_passage`, `get_passage`, `resolve_quote`, `validate_link` APIs. It also provides separate `resolve_legacy_quote`, presented-range validation and chat-call recording. Snapshot identity covers chunk ID, source/corpus, file/text hashes, physical locator, exact indexed text and extraction/index-format versions. Persisted snapshots are written once, with an exclusive lock and atomic replacement; repeated additions validate existing bytes rather than overwrite them.
- Assessment schema v2 embeds source snapshots, legal anchors, retrieved candidate IDs, exact per-call source ranges/hashes, draft-call bindings and per-claim raw evidence links. Mutations cannot remove or replace old snapshots. Schema-v1 canonical/history files are upgraded in memory without rewriting archived bytes or inventing missing provenance; the next explicit mutation writes schema v2.
- The complete dense/BM25 candidate union is captured before the fusion cap. Reranking, drafting and final citations retain distinct sets. Device snapshots must match the already validated source manifest. Legal snapshot identity must match the requirement's hash/source/chunk/page/block. A hash mismatch is an execution failure before drafting, not a finding of missing documentation.
- Model inputs are logged before inference. Each trace names its stage/model, hashes instructions/input, identifies actual source ranges, and records started/completed/failed outcome. Declared ranges must occur in the actual input. Interrupted calls remain started (completion unknown). Draft/answer context currently shows at most 2,200 characters per device/source passage; a citation outside that shown range is rejected even if it appears in the full snapshot. Reranking sees its own candidate pool/full ranges.
- Review drafts request a typed claim inventory. Deterministic validation rejects invented IDs, ambiguous/repeated quotes without chosen offsets, wrong corpus roles, absent or mismatched spans and citations outside the bound draft call. Missing inventories/unverified legal anchors/citation defects result in `needs_review`. Rejected model references remain in the canonical draft for diagnosis; only validated links and exact raw references enter published findings.
- Legal and device sources share the same buffer representation. The existing normalized `core.is_real_quote` extraction validator is unchanged. Legacy legal quotes can be mapped through case folding, whitespace, soft-hyphen and hyphen normalization to a unique raw span; the published quote is the actual indexed substring. Ambiguous/unmappable anchors are flagged and suppressed as exact quotations. New extraction stores raw anchor links or an explicitly unresolved normalized anchor.
- `ask` now validates exact raw claim quotations/context membership and keeps its existing separate support-model pass. Extraction and ask store immutable snapshots under `state/source_buffer/` and unique local logs under `state/evidence_runs/`. Optional CLI evaluation reranking uses the recorder as well. These logs retain model outputs as explicitly unvalidated draft outputs. Embedding operations are not chat-call/claim audits.
- Compatibility reports retain their established fields and add raw provenance. Markdown uses literal blocks to preserve quotation whitespace. Imported original reports remain in canonical provenance; compatibility exports do not republish their unaudited quotations as newly verified exact references. Historical schema-v2 reports reproduce their raw evidence and report content after source/index changes without consulting the current corpus.

## Verification

Commands used with the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage2-before
# 70 passed before changes
.\.venv\Scripts\python.exe -m pytest -q --basetemp reports/test-temp-stage2-final
# 116 passed after implementation
.\.venv\Scripts\python.exe -m pytest tests/test_report_state.py::test_legacy_import_preserves_ids_status_and_limitations tests/test_report_state.py::test_partial_legacy_resume_integrates_register_without_double_counting tests/test_source_buffer.py::test_old_snapshot_reproduces_report_after_reindex_and_source_changes -q --basetemp reports/test-temp-stage2-exports
# 3 passed after the final compatibility-export clarification
.\.venv\Scripts\python.exe main.py --help
git diff --check
```

All checks passed; no new regressions. The 46 new synthetic cases cover immutable/disk snapshots, unknown/unsafe IDs, wrong hashes/locators/offsets, changed source and version identities, tamper rejection, repeated-quote offsets, overlap traceability, PDF versus DOCX locators, reversible legacy normalization (including Unicode casefold expansion), strict raw quotation/context checks, missing raw legal anchors, candidate/presented/cited separation, complete backend candidate union, manifest mismatches before drafting, separate reranker/draft contexts, failed-call traces, answer abstention, extraction provenance, schema-v1 read-only upgrades, and historical report reproduction. Existing fixture changes add source metadata and isolated legal chunks required by the new provenance contract; old behavioral assertions remain, with the newly published audit label updated to `raw_spans_checked`.

## Preservation and limits

Verification involved no live inference, real-corpus extraction/review/migration, model download or index rebuild/deletion. Only source, tests and documentation are included in the implementation commit; no push was performed. The user's `.env`, source documents, device profile, existing register/manifest, vector database and generated assessments were not changed. All executable workflow tests use synthetic sources and mocked models in dedicated ignored `reports/` test folders. No confidential document content or API credentials were printed. Live model availability was not rechecked for this stage.

Raw spans address exact **indexed extracted text**, not original PDF bytes or stable Word pages; earlier parsing/chunking transformations remain. Snapshot/file metadata is supplied by the existing validated index/manifest. Raw provenance does not establish semantic entailment, completeness of the model's claim inventory, applicability, legal accuracy or compliance. The new review audit is labelled `raw_spans_checked`; independent semantic/claim-coverage review remains Stage 6. Cross-encoders, multi-query planning, calibrated evidence gates and six-role orchestration are not implemented here. Snapshot/chat artifacts contain source excerpts/model drafts and remain local; no cleanup/migration removes old snapshots.
