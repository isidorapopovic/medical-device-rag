# Codex Task 05 — Streamlit MedTech VC dashboard, grounded memo, and evaluation

## Prerequisites
Tasks 01–04. Build on **existing** `streamlit_app.py` and current local model/report utilities. Do not replace the original medical-device upload/preview or MDR workflows.

## User-facing flows
Add a clearly separated **VC Research** section/tab:
1. **Company explorer:** search/filter the imported 50-company dataset and view source URLs, missing values, regulatory claims vs verified findings, related investor rows, and VC glossary explanations.
2. **Startup evaluator:** enter/edit structured device profile or upload a deck; display extracted claims with source page references, top comparable FDA 510(k) devices, closest companies, investment relationships, evidence gaps, and confidence/coverage.
3. **Research memo:** generate/export evidence-grounded Markdown and JSON memo, with eight sections: company overview; clinical problem; analogous cleared devices; competitive differentiation; clinical evidence; regulatory considerations; investor/funding comparables; diligence questions and risks.
4. **Evaluation:** load manually annotated comparable-device relevance labels; report Recall@5 and Precision@5 plus citation validity and simple extraction-field accuracy when labels exist. Do not construct ground truth from model outputs.

## Grounding / evidence contracts
Every factual claim in the memo must include source reference (input filename+row, FDA decision ID+official URL, original deck+page, or verified paper metadata) or explicit `unverified/unknown` tag. Separate `startup_claim`, `public_source_fact`, `model_inference`, and `analyst_assessment`. Reference unknown facts as gaps, not asserted negatives. Do not generate fabricated citations, clearance identifiers, clinical study outcomes, revenues, valuations, fund performance, or investment recommendations framed as proven predictions. If using LLM, pass only retrieved context, validate structured output against source IDs, and offer deterministic report generation when local Ollama is unavailable.

## Optional transparent scoring — not investment prediction
Implement a **configurable analyst screening rubric**, not a probability of VC success. Default categories/weights:
- regulatory feasibility: 20%
- clinical evidence quality: 20%
- technology differentiation: 20%
- commercial potential: 15%
- business/financial viability: 15%
- team/execution: 10%

Each criterion receives `score: null|0..5`, `reason`, `evidence_ids`, `confidence`, `missing_inputs`, `reviewed_by_human`. A missing/unverified criterion should remain `null` and reduce **coverage**, not receive an automatic 0 or an invented neutral score. Calculate score only over rated criteria and display `rated_weight / total_weight` coverage prominently. Guard against rankings when coverage is poor; never claim calibrated predictive ability. Allow user to disable scoring entirely. Explain that numerical weights are subjective defaults and not trained/validated investment forecasts.

## Streamlit and privacy constraints
- Existing interface and CLI must remain usable; no API keys required to browse local dataset.
- Use existing local Ollama if available; fail gracefully when unavailable.
- Keep uploads local, prevent filename collisions/path traversal, cap upload size, and avoid logging pitch-deck text to console.
- Existing app has **no authentication**. Explicitly recommend localhost-only and do not expose it externally for confidential decks.
- Do not automatically download public PDFs or send private decks to third-party services.

## Concrete artifacts
- `vc_engine/memo.py`, `vc_engine/scoring.py`, `vc_engine/evaluation.py` (names flexible).
- Streamlit UI integrated in existing entry point or a second VC app that is linked from it.
- `reports/vc/<profile-id>/memo.md`, `memo.json`, `comparables.json`, `scorecard.json`; sanitize IDs and avoid overwrites.
- `eval/vc_gold_comparables.json` template with *empty* examples / annotation instructions, and evaluation CLI.
- README describing data import → FDA fetch/cached search → startup comparison → export, plus offline fallback.

## Acceptance tests
- End-to-end smoke path works locally from all three CSVs and a synthetic startup profile, without network and without Ollama (using cached/synthetic FDA records clearly labeled fixtures).
- No scoring value is fabricated for missing revenue/team/clinical evidence; low-coverage score is visibly caveated.
- Memo never cites an unknown source ID; wrong/invented IDs are dropped and associated claims marked `needs_review`.
- All fields in a funding table retain currency, amount type, and data source.
- Existing app still runs; `python -m pytest -q` passes.
- Codex outputs edited files, test commands/results, screenshots if feasible, and a candid limitations list.

## Implementation order within this task
Start with deterministic Markdown/JSON memo and tests, then add Streamlit screens, then optional LLM narrative generation, then scoring/evaluation charts. Prioritize verifiable research utility over decoration.
