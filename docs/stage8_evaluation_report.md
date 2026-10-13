# Stage 8 evaluation report

Recorded on 2026-10-13. This is an availability and implementation-verification report, not measured project accuracy.

| Item | Observed result |
|---|---|
| Human gold cases in `eval/gold_queries.json` | 0 |
| Calibration / held-out human split sizes | 0 / 0 |
| Existing registered requirements | 15 |
| Sources in the existing index manifest | 3 |
| Existing index matches current documents | No: files were added or removed since indexing |
| `python main.py inspect` | Passed, exit code 0 |
| Hybrid device `explore` | Blocked before inference by index/source mismatch, exit code 1 |
| Real retrieval / grounding accuracy | Not measured |
| Real median/p95 inference latency / model peak memory | Not measured |
| New calibration threshold | None created |

The existing index, requirement register and `.env` were preserved. The proposed real review/resume/render sequence was not run: a matching index and human-verified gold are prerequisites, and the sample assessment ID must not overwrite an existing assessment. Inspection excerpts and manifest source hashes were recorded locally in ignored `reports/stage8-preflight/inspect.private.txt` and `availability.private.json`; they are not included in this public report.

Production-path evaluation now supports dense, BM25, hybrid, multi-query hybrid, multi-query cross-encoder, and full gate/reviewer experiments. None/LLM complete-pipeline variants can be selected explicitly. Each experiment records actual case/split counts, candidate/query caps, backend/model identity, score transformation, source hashes, prompt/planner fingerprints, token/context limits, failures, memory measurement scope and timing. A missing optional model or scoring/reviewer failure is not counted as a successful abstention. Uncalibrated strict-mode abstention remains visible and does not prove a useful threshold was validated.

Synthetic tests exercise the real candidate/fusion/reranking and review orchestration using mocked providers. Their numerical values and timings are engineering fixtures, not evidence of MDR retrieval quality, legal completeness or real CPU performance. Human-adjudicated support and contradiction misses remain unmeasured until frozen published claims are reviewed independently. Model verdicts are never used as human gold.

## Dataset work remaining

No qualified human labels were supplied, so claiming 20–50 validated examples would be misleading. Use the new example formats only as worksheets. Independently label diverse positive, hard-negative/unanswerable, ambiguous, qualification/exception, cross-document, historical/version and injection cases after opening the original documents. Record the actual sample size. Full review cases must reference distinct existing requirement IDs; retrieval-only questions may use a broader set. Do not reuse a question or requirement across calibration and held-out splits.

Resolve the index/source mismatch deliberately before collecting gold. Pin every corpus source hash and the uploaded legal-version label, then use calibration-only data to create a threshold artifact and keep held-out cases separate. Small splits remain exploratory. After this work, run the comparison under a distinct run ID, independently adjudicate frozen claims and report failures alongside retention/abstention and timing rather than presenting a single success percentage.
