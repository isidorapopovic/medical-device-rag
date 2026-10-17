# Test matrix and failure injection checklist

For **every** new stage:

| Group | Scenarios | Expected behavior |
|---|---|---|
| Invalid input | nulls, missing fields, wrong MIME, huge file, unicode, traversal | deterministic validation error, no partial unsafe mutation |
| Model failure | offline, model not installed, timeout, 429/503, malformed JSON | bounded retry only when transient, state blocked/needs review |
| Budget | call limit, total tokens, timeout, cloud disabled | no extra call, persist partial state, report exhausted limit |
| Evidence | no results, weak retrieval, wrong quote, wrong page, stale hash | abstain/reject and flag for review |
| Legal coverage | outdated edition, partial subset, draft clauses | no silent full-coverage claim |
| Privacy | injected instructions, cross-project query, secrets in error | data isolated, text treated as untrusted |
| Storage | duplicate events, concurrent jobs, interrupted writes, migration | idempotent and recoverable |
| Regression | baseline CLI/Streamlit, existing tests | no unexplained breaking behavior |

Testing pyramid: unit (fake models, no net) -> component (temp SQLite/Chroma or stub) -> integration (optional Ollama) -> expert labeled end-to-end review. Any test not run must be marked **NOT RUN**. Use existing formatting/testing toolchain where possible rather than adding many frameworks.

## Standard stage report template

```text
STAGE:
CHANGED FILES:
FEATURE FLAGS / DEFAULTS:
TESTS:
  command | result | count | remarks
INTEGRATION TESTS NOT RUN:
ERROR/FALLBACK CHECKS:
RUNTIME AND MODEL CALLS:
MIGRATIONS/COMPATIBILITY:
KNOWN RISKS:
ROLLBACK:
NEXT STAGE:
```
