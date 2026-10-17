# Stage 08 — Orchestrated workflow, ReportState, SourceBuffer, budgets

## Goal
Make analysis resumable, bounded, testable and idempotent without a heavy multi-agent framework.

## Implementation
1. Create deterministic orchestrator states `queued -> parsing -> profile_review -> registry_ready -> applicability -> retrieval -> audit -> report_draft -> needs_review|completed_with_gaps|blocked`. Human hold gate before high-impact review; workflow checkpoints in SQLite.
2. `ReportState`: per-requirement versions/findings + review history; `SourceBuffer`: immutable source references tied to each claim/finding. Cache by project + doc SHA/versions + registry edition/revision + model + prompt version + retrieval version. Invalidate only affected findings after changes.
3. Three LLM roles max, same model allowed. Budget manager from Stage 01 with 30-call default, max input chars/output tokens, per-call timeout and overall deadline; bounded concurrent tasks (1 by default on CPU). Use deterministic recommendation templates if role C disabled.
4. Retry only transient failures (429, 503, temporary model busy); max 2 retries beyond first, exponential backoff with jitter and deadline. Schema-invalid output: at most one repair attempt within same global attempt budget; permanent errors no retry. Persist job checkpoints and idempotency keys.
5. UI/workflow can pause, cancel, resume; cancelled run yields partial clearly marked report, not full completion. Ensure restart-safe locks and only one active run per same input snapshot.
6. Expose run summary: counts, model calls, estimated/measured tokens, local/cloud cost (if known), retrieval and inference latencies, missing spans/requirements, exhausted budget.

## Tests
- Crash between audit and save, run twice same input, user cancels, model slow/hung, budget hit mid-requirement, SQLite write failure, two simultaneous runs, input file changes during run, forced error in every workflow stage; partial updates preserve prior verified findings.

## Gate
Idempotency, timeout, cancel/resume, stale invalidation and budget test suite pass offline with FakeLLM. No unbounded role loops. LangGraph is **not required**.
