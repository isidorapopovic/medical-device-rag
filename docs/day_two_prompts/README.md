# Product A — Regulatory Compliance Intelligence | Codex execution pack

> Target repository: https://github.com/isidorapopovic/medical-device-rag  
> Product: auditable, evidence-grounded EU medical-device documentation gap assessment.  
> Scope: Product A only. **Do not implement patents, patentability, FTO, or IP search.**

## Read this first

These files are implementation instructions for Codex inside your existing repository. This pack is *not* a claim that features have already been implemented or validated. In the repository open Codex at the project root. Copy the `stages/` directory, `AGENTS.md`, and `reference/` into the repository, commit the plan, then work stage-by-stage.

The public README at review time describes `main.py`, `streamlit_app.py`, `mdr_rag/`, local Ollama (`qwen3:4b`, `embeddinggemma`), Chroma, BM25/RRF, `requirements_draft.json`, JSON/Markdown reporting, basic evaluations, and `rag.py` as a legacy Gemini prototype. **Stage 00 must verify the live working tree and treat it as authoritative.** The source clone was not accessible to this pack-generation environment; do not assume undocumented modules or functions exist.

## Key policy

This is an **evidence review assistant**, not an EU MDR conformity assessment, notified body, clinical advisor, or legal counsel. It never says a device is certified, CE marked, legally compliant, or noncompliant solely from missing uploads. Keep the distinction: regulation requirement, applicability, document coverage, factual support, specialist-reviewed conclusion. Never invent legal requirements, clauses, page numbers, harmonized-standard obligations, clinical data, citations, approvals, benchmark scores, or patient files. If a legal registry is incomplete, show **coverage incomplete** prominently.

## Implementation order and gates

| Stage | File | Deliverable | Must pass before next |
|---|---|---|---|
| 00 | `stages/00_REPO_AUDIT_AND_BASELINE.md` | audit, characterization and baseline | old CLI works/tests run or documented blockers |
| 01 | `stages/01_FOUNDATIONS_AND_CONTRACTS.md` | schemas, config, logs, budgets, SQLite | schema/unit tests |
| 02 | `stages/02_DOCUMENT_INGESTION_AND_PROVENANCE.md` | verified document extraction and provenance | parser/edge-case tests |
| 03 | `stages/03_DEVICE_PROFILE_AND_REVIEW.md` | editable evidence-linked profile | extraction and review tests |
| 04 | `stages/04_REGULATORY_REGISTRY.md` | curated, versioned MDR registry | no unverified items activated |
| 05 | `stages/05_APPLICABILITY_ENGINE.md` | traceable applicability | unknown not converted into no |
| 06 | `stages/06_RETRIEVAL_AND_RERANKING.md` | measured retrieval improvements | baseline and regression metrics |
| 07 | `stages/07_EVIDENCE_AND_CITATION_AUDIT.md` | per-requirement evidence findings | negative/adversarial tests |
| 08 | `stages/08_WORKFLOW_REPORTSTATE_AND_BUDGETS.md` | resumable workflow, cache, retries | fault-injection tests |
| 09 | `stages/09_EVALUATION_AND_RELEASE_GATES.md` | offline benchmark and honest scorecard | release thresholds and slices |
| 10 | `stages/10_STREAMLIT_UI_AND_REPORTS.md` | reviewer workspace and exports | UX/end-to-end tests |
| 11 | `stages/11_SECURITY_CI_AND_OPERATIONAL_READINESS.md` | secure local demo + CI | security and regression checks |
| 12 | `stages/12_END_TO_END_ACCEPTANCE.md` | final audit and demo | all release gates |

## How to instruct Codex

For each stage, paste into Codex:

```text
Read AGENTS.md, README.md, and reference/ARCHITECTURE_AND_ACCEPTANCE.md, then execute stages/XX_*.md exactly, against my current repository. Inspect relevant implementation and tests before changes. Implement a minimal coherent increment, add tests and migration notes, run all available offline checks, and report file diffs, commands, results, unresolved issues, runtime/API cost, and any skipped tests. Do not silently change legacy CLI behavior, fabricate legal content, or claim a test passed if not run. Stop before starting the next stage.
```

Do not paste all stage files to Codex at once; Codex should finish, test and commit each stage separately. If CI or models are unavailable, mark **NOT RUN**, run deterministic unit tests, and provide the exact reproduction command. Never treat skipped model integration tests as passing.

## Environment and cost

- Windows PowerShell + Python 3.11 or 3.12; Ollama local default; no GPU required.
- Use current pinned dependencies where appropriate; new heavy dependencies optional and isolated.
- Local deterministic tests must run without network, Ollama, API keys, or downloaded model weights.
- Cloud LLM off by default. Never send private files externally without explicit project opt-in.
- Example starting budgets (configurable, not guaranteed price estimates): max **30** LLM calls per project analysis, **120,000** input tokens and **16,000** output tokens total where usage is reported, max **3** rerun attempts per failed task including first execution, **$0** cloud spend by default. For Ollama, record calls and timing even if cost is $0.
- If token metering is not supported, count calls/context characters conservatively and label token totals **estimated**; budget checker must enforce hard limits on known quantities and a conservative estimated limit for unknown quantities.
- Large dossiers should be chunked, capped, and resumed, not stuffed into prompts.

## Suggested commands (Codex must adapt to existing CLI)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python main.py --help
python main.py inspect
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Initial legal verification references:
- https://eur-lex.europa.eu/eli/reg/2017/745/oj/eng
- https://health.ec.europa.eu/medical-devices-sector/new-regulations/guidance-mdcg-endorsed-documents-and-other-guidance_en

The program must not assume those URLs are always current/consolidated or automatically fetch them without a defined legal content ingestion process.

## Definition of success

User can upload a set of device documents, review an extracted device profile, select a **verified, versioned** legal requirement set, receive a requirement-by-requirement applicability and document-evidence status with source quotes, identify missing documentation, edit reviewer decisions, and export a traceable report. A complete end-to-end offline test works without any paid API.
