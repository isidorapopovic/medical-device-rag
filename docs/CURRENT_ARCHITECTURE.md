# Current architecture — Day Two Stage 00

Audited 2026-10-16 against the live working tree. This is a characterization, not a release approval. Instructions: `day_two_prompts/START_HERE_CODEX_PROMPT.md`. Existing application files are preserved.

## Entry points and data flow

`main.py` loads root `.env` with python-dotenv (existing process variables win), parses arguments, then dispatches to shared modules. `streamlit_app.py` only uploads/downloads/previews files; it does not run the assessment workflow. `rag.py` is a separate unsupported Gemini prototype; it is neither imported nor migrated here.

| Command | Flow and outputs / side effects |
|---|---|
| inspect; locate PHRASE | `pipeline.inspect_files`: creates missing corpus folders, reads files; prints physical PDF pages and previews/search matches. Non-PDF files only list their type. No inference. |
| index | `pipeline.run_index` -> `search.rebuild_index`; reads both corpora, deletes/recreates Chroma `medical_mdr_evidence`, embeds batches of 32, writes `state/manifest.json`. Empty input fails before database access. Rebuild is destructive to that collection and is not a baseline check. |
| ask QUESTION | Checks manifest/hashes, retrieves legal and device passages, drafts and checks claims, prints supported answer or abstention, persists evidence trace under `state/evidence_runs`. |
| extract --pages SPEC [--legal-file NAME] | Requirement Analyst reads selected indexed legal pages, uses local structured generation, saves draft register `state/requirements_draft.json`, immutable register revisions and evidence traces. These are drafts, not a verified registry. |
| review | `roles.AssessmentOrchestrator` -> `review_state`: applicability, bounded query planning/retrieval, relevance gate, drafting, citation and separate claim review, bounded repair; persists assessment checkpoints/revisions, evidence snapshots, JSON/Markdown compatibility reports. Strict uncalibrated relevance gate abstains. |
| report --assessment-id ID | Renders saved state; historical rendering is explicit. Exports contain sensitive excerpts. |
| import-legacy | Imports into a new assessment ID as unverified; preserves source report. |
| explore QUESTION | Prints candidates for manual labeling. |
| visualize-embeddings | Reads stored vectors; optional query embedding; writes self-contained HTML and companion JSON. |
| evaluate | Production retrieval/full-review comparisons or offline frozen adjudication; JSON/Markdown metrics and optional private assessment snapshots. Gold labels must be human reviewed. |
| calibrate-gate | Reads independently labeled saved scorer runs, writes new calibration artifact without inference. |
| graph | Reads saved assessment (default `reports/assessment.json`), exports citation graph HTML/JSON; not graph retrieval. |
| Streamlit | `document_ui.save_uploaded_document` uses exclusive creation; PDF/DOCX/TXT/MD, 50 MiB UI limit, category routing and no overwrite. Preview cap 12,000 characters. No authentication. Launch only on 127.0.0.1. |

## CLI contracts

Global options precede subcommands: `--retrieval dense|bm25|hybrid`; mutually exclusive `--rerank` (forces LLM) and `--rerank-backend` / `--reranker none|llm|cross_encoder`.

Additional flags: review `--limit --k --assessment-id --use-env-config --resume --requirement-id --refresh`; report `--assessment-id --use-env-config --historical --revision`; import-legacy `--assessment --assessment-id`; explore `--kind --k`; visualize-embeddings `--sample --query --out`; evaluate `--gold --ks --out --compare-all --methods --run-id --saved-evaluation --grounding-labels --gate-labels --gate-calibration`; calibrate-gate `--labels --out`; graph `--assessment --out --max-requirements`. Invalid argparse input exits 2; selected execution errors print `ERROR:` and return 1. Not every provider exception is caught by the CLI.

## Modules and state

- `core`: SHA-256 identities, character chunking (2000/250), physical PDF pages, DOCX/text blocks, source collection routing and citation locations.
- `schemas`, `roles`, `applicability`: typed outputs, role facades, profile-linked applicability.
- `search`, `query_planner`, `retrieval_trace`: dense/BM25 with RRF, at most four queries, 12 per backend/query and 30 merged candidates. BM25 cache is process-local, keyed by corpus/fingerprint; BM25 still reads Chroma documents but calls no embedding model.
- `reranking`, `rerank_state`, `download_reranker`: optional local LLM or pinned CPU cross-encoder; explicit provisioning separate from inference.
- `source_buffer`, `review_evidence`, `claim_audit`, `review_validation`: immutable extracted text snapshots, presented ranges, raw spans, claim inventory and audit.
- `report_state`, `review_state`, `saved_configuration`, `requirement_identity`, `requirement_analyst`: JSON state, locks/atomic revisions, invalidation/resume, saved configuration, register identity.
- `evidence_gate`, `gate_evaluation`: strict calibration binding and offline calibration/evaluation.
- `evaluation`, `experiments`, `grounding_evaluation`: production-path evaluation and independent frozen claim labels.
- `Q_Mix_report_writer`, `embedding_viz`, `graph_viz`: Markdown, PCA/health visualization and citation graph exports.
- `config`: validated Ollama context and GPU-layer options. `document_ui`: upload storage helper. `__init__`: package marker.

Root paths are derived from `core.py`, not the caller's working directory: `documents/legal`, `documents/device`, optional `documents/device_profile.json`, `vector_db`, `state`, `reports`. Chroma collection differs from legacy Gemini. Citation contract is `[source ID] filename, PDF page N`, or text block with no stable page number. Source records include source path, file hash, corpus kind, page/block and deterministic content-derived ID; immutable review spans add exact offsets and text hashes.

## Pack assumptions requiring adaptation

The live app already implements substantial Day One persistence, provenance, planning, gating and review. Preserve these rather than recreate them. Storage is versioned JSON, not SQLite; no migration is authorized in Stage 00. Current supported names are `RERANK_ENABLED`, `RERANK_BACKEND`, `CROSS_ENCODER_*`, not proposed `RERANKER_ENABLED`. Proposed run-wide budget/cloud/OCR settings are not implemented merely by adding environment variables. Current six-role orchestration differs from the pack's three logical LLM roles. Preserve all 13 CLI commands, including commands omitted from the pack's basic list. A reviewed versioned legal registry and full reviewer UI are future work.

Dependency ranges are in requirements.txt; optional model stack pins are in requirements-rerank.txt. No formatter/linter configuration was found. See BASELINE_AND_RISKS.md for measured commands and limitations.

## Actual top-level symbol inventory

- `mdr_rag/__init__.py`: 
- `mdr_rag/applicability.py`: `ProfileFact`, `ApplicabilityResult`, `ApplicabilityAnalyst`
- `mdr_rag/claim_audit.py`: `exact_inventory`, `CitationAuditor`, `bindings`, `render_finding`, `validation_policy`, `failure_finding`, `render_validated_finding`, `model_payload`, `section_bindings`
- `mdr_rag/config.py`: `ollama_num_ctx`, `ollama_gpu_layers`, `ollama_device_options`
- `mdr_rag/core.py`: `digest`, `norm`, `is_real_quote`, `is_raw_quote`, `parse_pages`, `chunks`, `source_records`, `make_record`, `all_records`, `location`, `validate_ids`
- `mdr_rag/document_ui.py`: `save_uploaded_document`
- `mdr_rag/download_reranker.py`: `download`
- `mdr_rag/embedding_viz.py`: `unit_vectors`, `embedding_statistics`, `visualize_embeddings`
- `mdr_rag/evaluation.py`: `load_gold`, `relevant_label`, `rank_scores`, `fusion`, `evaluate`, `inspect_candidates`
- `mdr_rag/evidence_gate.py`: `fingerprint`, `GateModel`, `GateContext`, `gate_context`, `Calibration`, `immutable_scorer`, `settings`, `AtomicObligation`, `obligation_inventory`, `PassageDecision`, `GateDecision`, `screen`
- `mdr_rag/experiments.py`: `load_dataset`, `latency_summary`, `public_claim_id`, `library_versions`, `memory_summary`, `_validate_labels`, `_precision`, `_queries`, `_review`, `evaluate_production`, `write_evaluation_markdown`
- `mdr_rag/gate_evaluation.py`: `HumanPassageLabel`, `LabelCase`, `ReviewedLabels`, `load_labeled_runs`, `validate_cases`, `metrics`, `tune`, `calibrate_labels`, `evaluate_labels`
- `mdr_rag/graph_viz.py`: `build_evidence_graph`, `draw_graph`, `graph_from_assessment`
- `mdr_rag/grounding_evaluation.py`: `ClaimLabel`, `CaseLabel`, `Adjudications`, `adjudicate`
- `mdr_rag/pipeline.py`: `now`, `save_json`, `load_json`, `llm_parse`, `inspect_files`, `run_index`, `check_manifest`, `choose_legal_source`, `extract_requirements`, `profile_data`, `evidence_context`, `answer_claims_are_supported`, `check_regulation_alignment`, `run_review`, `run_ask`
- `mdr_rag/Q_Mix_report_writer.py`: `clean`, `raw_quote`, `write_markdown`
- `mdr_rag/query_planner.py`: `PlannedQuery`, `QueryPlan`, `PlannerSelection`, `PlannerPersistenceError`, `canonical`, `plan_queries`
- `mdr_rag/report_state.py`: `timestamp`, `fingerprint`, `StateModel`, `RequirementRecord`, `RetrievedPassage`, `Dependencies`, `RequirementSection`, `StageEvent`, `ReportState`, `validate_assessment_id`, `atomic_replace`, `atomic_write`, `exclusive_lock`, `StateStore`, `invalidate`, `decode_state`, `compatibility_report`, `export_report`, `import_legacy`
- `mdr_rag/requirement_analyst.py`: `extract_register`
- `mdr_rag/requirement_identity.py`: `anchor_key`, `assign_identity`
- `mdr_rag/rerank_state.py`: `ScoredSpan`, `RerankDiagnostics`
- `mdr_rag/reranking.py`: `digest`, `backend_selection`, `cross_encoder_settings`, `cache_folder`, `provisioned_folder`, `library_versions`, `local_snapshot`, `_artifact_hashes`, `reranker_identity`, `CrossEncoderScorer`, `get_scorer`, `scored_copies`, `publish`, `active_backend`, `capture_scores`, `rerank_candidates`, `requirement_rerank_query`, `citation_rerank_coverage`
- `mdr_rag/retrieval_trace.py`: `TraceModel`, `BackendHit`, `CandidateTrace`, `QueryTrace`, `RetrievalTrace`
- `mdr_rag/review_evidence.py`: `prepare_legal_anchor`, `validate_finding`, `validate_obligation_coverage`
- `mdr_rag/review_state.py`: `reviewer_schema`, `configuration`, `corpus_hash`, `dependencies`, `scope_from_draft`, `new_state`, `synchronize`, `perform_stage`, `run_review`, `render_report`
- `mdr_rag/review_validation.py`: `validate_section`
- `mdr_rag/roles.py`: `VersionedRegister`, `RetrievalResult`, `AuditResult`, `ReviewedFinding`, `ReportExport`, `RequirementAnalyst`, `EvidenceRetriever`, `CitationAuditor`, `EvidenceReviewer`, `ReportWriter`, `AssessmentOrchestrator`
- `mdr_rag/saved_configuration.py`: `environment`, `scoped_environment`, `resolve`
- `mdr_rag/schemas.py`: `RequirementCandidate`, `RequirementBatch`, `QuotedReference`, `FindingClaim`, `ObligationCoverage`, `Finding`, `Answer`, `ClaimEvidence`, `AnswerClaim`, `AnswerSupportVerification`, `RerankScore`, `RerankBatch`, `StructuredClaim`, `StructuredFinding`, `ClaimVerdict`, `CoverageVerdict`, `FindingReview`, `StructuredAnswer`
- `mdr_rag/search.py`: `open_db`, `embeddings`, `rebuild_index`, `collection`, `_tokens`, `_llm_rerank`, `rerank_passages`, `reranking_enabled`, `hybrid_search`, `retrieve_candidates`, `legal_chunks`
- `mdr_rag/source_buffer.py`: `content_hash`, `ImmutableModel`, `SourcePassage`, `RawSpan`, `ClaimEvidenceLink`, `PresentedPassage`, `ModelCallTrace`, `checked_passage`, `normalized_offsets`, `occurrences`, `SourceBuffer`, `call_trace`, `EvidenceRecorder`, `recording`, `EvidenceRun`
