CODEX IMPLEMENTATION PACK — MedTech VC Intelligence

Run tasks in numerical order, sending one Markdown file to Codex at a time. Each file is a standalone task brief. Do not run all five tasks in one giant agent command.

1. 01_DATA_FOUNDATION.md
2. 02_FDA_REGULATORY_PRECEDENTS.md
3. 03_STARTUP_SIMILARITY_AND_CLINICAL_EVIDENCE.md
4. 04_VC_INVESTMENTS_AND_TERMINOLOGY.md
5. 05_VC_DASHBOARD_MEMO_AND_EVALUATION.md

Copy your three CSVs to the repository's data/vc/raw/ folder. Task 04 instructs Codex to create an editable data/vc/vc_terms.yaml glossary file, so terms are not buried in model prompts.

Codex starter prompt: "Read the attached task Markdown and inspect the actual repository before making changes. Implement only this task, preserve all existing MDR workflows, run the tests, and summarize edited files, commands, results, and limitations."
