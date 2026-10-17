# Stage 09 — Reproducible evaluation and safety-oriented release gates

## Goal
Measure retrieval, attribution, applicability and decision quality independently; detect regressions.

## Implement
1. Create `eval/datasets/README.md` with source/licensing, annotator, split date, version, labeling guidelines, allowed uses. Separate toy synthetic integration fixtures from real expertly adjudicated benchmark. Never invent regulatory ground truth.
2. Gold label JSONL schema: `case_id, project_fixture_id, edition_id, question, expected_requirement_ids, relevant_span_ids, applicability_label, evidence_status_label, expected_supported_claims, unanswerable, difficulty_tags, annotators, adjudication_state`. Only adjudicated cases contribute release score.
3. CLI evaluator runs retrieval baseline (BM25/dense/hybrid/rerank), role B grounded decision, citation validator, and report action coverage. Deterministic metric calculators run without models from stored predictions.
4. Calculate Recall@1/5/10, MRR, nDCG, evidence status macro/micro F1, per-class confusion, applicability accuracy, false-supported rate, citation validity, citation support judged by human, abstention precision/recall, cost/call/latency percentiles. `not_found` is not negative evidence. Add missing-source slice, scanned-page slice, outdated-regulation slice, conflicting evidence slice, bilingual, prompt-injection.
5. Confidence intervals/bootstrap where sample size permits; report N and `not evaluable` for zero denominators. Version retrieval, prompts, model, dataset and random seeds. No arbitrary score claims.
6. Regression gates: citation references validity 100% in deterministic cases; adversarial fake citations blocked 100%; target Recall@10 >= .90 and evidence macro F1 >= .80 on adjudicated cases as *provisional*, fail release if critical false-supported cases unresolved. Do not overfit test set; allow threshold update only with documented rationale.
7. Create `eval/reports/` with machine-readable JSON + human-readable markdown and per-case error investigation including false-supported and missed applicability results.

## Tests
- Duplicate labels, empty gold set, missing relevance judgments, zero positives, prediction coverage, invalid span IDs, metric ordering, data leakage train/test, unanswerable answered confidently, reranking worsening accuracy, same seed reproducibility, broken provider.

## Gate
`python -m pytest -q` and `python -m <actual_eval_cli> --offline` pass on toy fixtures; real benchmark status clearly says NOT YET VALIDATED until expert labels available. No fabricated accuracy scores.
