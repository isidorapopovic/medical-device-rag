# Architecture and acceptance contracts

## Scope boundaries

In scope: EU MDR regulatory **documentation evidence gap assessment**, source links and regulatory editions, human review, evaluation. Out: IP, US FDA, automatic CE approval, patient diagnosis, automatic legal update claims, automatic standards text scraping, unattended legal determinations.

## Logical architecture

`Upload -> validation/scan -> immutable document+extraction -> structured profile -> legal-registry selection -> applicability -> evidence retrieval (BM25+dense optional+rerank optional) -> evidence verification -> findings -> recommendations -> human review -> report`.

## Three reusable LLM roles

A. Extraction/qualification: device profile with cited excerpts; proposed applicability only if legally grounded. B. Evidence analysis: support/refute/unresolved per requirement. C. Recommendation writing: editorial summary from accepted structured findings only. They may share **one** local model/runtime. Deterministic source verification + workflow scheduler are **not agents**. No autonomous free-form loops or unconstrained tool use. For low budget, disable role C and render templated recommendations from findings.

## Enumerations

- Requirement applicability: `applicable`, `not_applicable`, `conditional`, `unknown`, `requires_human_review`.
- Document evidence: `supported`, `partially_supported`, `contradictory`, `not_found`, `unverifiable`.
- Verification: `verified`, `needs_review`, `rejected`.
- Assessment: `draft`, `blocked`, `completed_with_gaps`, `reviewed`.
- Human review: `pending`, `accepted`, `overridden`, `rejected`.

**Never include `compliant` or `noncompliant` as a machine-issued terminal state.** Applicability is distinct from evidence. Contradiction is a positive finding of conflict, not lack of search results.

## Immutable provenance primitives

- `Document`: UUID, project_id, collection=`legal|device`, original name, MIME, SHA256, byte size, created_at, version, upload status.
- `SourceSpan`: stable ID, document_id/version, text_hash, extraction engine/version, section_path, physical_page_1based or null, block index or null, char offsets on normalized extracted page/block, literal text, quality flags.
- `RegulationEdition`: regulation ID, jurisdiction, source URL, published/amended/cutoff dates if verified, edition label, SHA256, currentness_status=`unverified|verified_as_of_date`, verified_by/date.
- `Requirement`: stable requirement ID, edition_id, legal span IDs, verbatim clause, applicability rules, effective date/verification state, reviewer notes. AI draft must be `unverified` until reviewed.
- `DeviceAttribute`: field name, value, source spans, status=`extracted|user_confirmed|unknown|conflicting`.
- `Finding`: requirement ID, edition ID, applicability, evidence status, distinct legal/device citations, rationale, missing items, next actions, reviewer decision, workflow/model/config version.
- `AssessmentRun`: run ID, project, frozen document versions, requirement-registry revision, prompts/model/embedding IDs, usage counters, timings, status and errors.

Stable citation form: `source_span_id` plus original filename, version, physical PDF page when available, verbatim snippet. Never infer PDF printed page from physical page. DOCX paragraph/block numbers are not pages. Reject nonexistent spans, wrong-document citations, offset/hash mismatch, and quotes not in extracted text (normalized whitespace policy explicit).

## Dependency boundaries

`schemas -> storage -> ingestion -> registry/profile -> retrieval -> analysis -> verification -> workflow -> UI`. Avoid circular imports. Keep provider interface injectable so unit tests use FakeLLM and FakeEmbeddings. Keep legacy adapters until old CLI tests pass. No hard-coded host paths.

## Recommended config keys

`LLM_PROVIDER=ollama`, `CLOUD_LLM_ENABLED=false`, `OLLAMA_LLM_MODEL=qwen3:4b`, `EMBEDDING_MODEL=embeddinggemma`, `RETRIEVAL_MODE=hybrid`, `RERANKER_ENABLED=false`, `OCR_ENABLED=false`, `MAX_LLM_CALLS_PER_RUN=30`, `MAX_PROMPT_CHARS_PER_CALL=16000`, `MAX_OUTPUT_TOKENS_PER_CALL=1200`, `MAX_RUN_OUTPUT_TOKENS=16000`, `MAX_CLOUD_SPEND_USD=0`, `RUN_TIMEOUT_SECONDS=1200`, `MODEL_REQUEST_TIMEOUT_SECONDS=120`, `MAX_RETRIES=2`, `LOG_LEVEL=INFO`, `APP_HOST=127.0.0.1`, `REQUIRE_HUMAN_REVIEW=true`. Validate overrides and fail on unsafe combinations (e.g., cloud provider with no explicit opt-in).

## Release gates

1. All deterministic tests pass offline; no severe regressions in old commands.
2. Legal requirement registry contains **only verified active entries**; uncovered law clearly labeled.
3. Every substantive output has a valid source or explicit unresolved label; deliberately injected fake citations are rejected in tests.
4. Missing evidence does not produce compliance/noncompliance conclusions. Null/unknown values remain unknown.
5. Evaluation metrics computed from versioned human-labeled cases, not LLM-created gold labels. Scores split by requirement family and evidence class.
6. All budget/time caps and transient/permanent failure behaviors tested.
7. Full local UI path works from sample upload through report; export preserves citations/edits.
8. No user content in logs; no cloud calls without explicit opt-in; multi-project isolation tested.

## Recommended evaluation thresholds (initial provisional gates, not validated safety claims)

Citation ID/offset validity: 100% on deterministic tests; unsupported legal claim blocking: 100% on adversarial fixture set; retrieval Recall@10 >= 0.90 on held-out expert labels before adopting new retriever; evidence decision macro-F1 >= 0.80 as an initial pilot target, with all false-supported cases manually reviewed; no unresolved critical errors in release review. If sample count is small, show confidence intervals and mark gate as provisional. Targets do not substitute for regulatory expert validation.
