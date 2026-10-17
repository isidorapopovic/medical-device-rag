# Stage 11 — Secure local operation and CI

## Goal
Prepare for private pilots, not claim enterprise production readiness.

## Implementation
1. Threat model: malicious PDFs/DOCX, zip bombs, parser exploits, prompt injection, data exfiltration, multi-project leakage, document indexing mix-ups, insecure logs, stale edition, external model calls, SSRF when optional URLs arrive.
2. Enforce localhost-only UI, no network serving by default, maximum upload sizes, allowed MIME/type sniffing, safe paths, temp directory cleanup, document retention/deletion, rate/request quotas, secrets environment only, no source passages in logs.
3. Project scoping enforced at SQLite queries, vector retrieval filters, cached results and exports. Add test for unauthorized cross-project source retrieval. If authentication missing, prominently document local single-user only and **block external deployment**; do not fake production auth.
4. CI GitHub Actions with Python 3.11/3.12: install from locked/pinned compatible dependencies, lint/format/check, offline pytest, security scan feasible without secrets; no external models/GPU in CI. Mark optional integration tests separately.
5. Add model-integration test scripts runnable intentionally on developer machine, Ollama readiness check, setup docs for Windows VS Code, basic diagnostic command, troubleshooting of missing weights/ports and corrupted indexes.
6. Document privacy policy decisions, third-party provider consent, known gaps, incident/restore runbook, backups and migration repair.

## Tests
- Attempt path traversal, project ID spoof, document injection, key leakage through exception, malicious URL (if URL ingestion enabled), oversize upload, corrupted cache, export directory escape, authentication absent at public bind, secret committed to git.

## Gate
All CI offline checks green; no cloud transfer without opt-in; deployment blocked or clearly local-only until auth, access control, security review and privacy documentation are complete.
