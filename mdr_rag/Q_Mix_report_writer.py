"""Local Q-Mix-style deterministic report writer (not an external Q-Mix API)."""
from pathlib import Path


def clean(text) -> str:
    return str(text).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def write_markdown(assessment: dict, destination: Path) -> None:
    rows = assessment["findings"]
    out = [
        "# EU MDR Regulatory Evidence Gap Review (DRAFT)",
        "",
        "> **Not a declaration of conformity, legal opinion, or certification.**",
        "> The findings are based only on selected pages of an uploaded legal text and uploaded device evidence.",
        "",
        f"- Generated (UTC): {assessment['generated_at_utc']}",
        f"- Uploaded law label: {assessment['legal_version_label']}",
        f"- Law document: `{assessment['legal_source']}`",
        f"- Assessed PDF pages (1-based): {', '.join(map(str, assessment['selected_pdf_pages']))}",
        f"- Device: {assessment['device_profile'].get('device_name', 'UNSPECIFIED')}",
        f"- Model: `{assessment['model']}`",
        f"- Requirements assessed: {assessment['assessed_requirements']} / {assessment['total_extracted_requirements']}",
        f"- Partial run: {'YES' if assessment['partial_run'] else 'NO'}",
        f"- Human validated: NO",
        f"- Snapshot: {'HISTORICAL — not validated against current inputs' if assessment.get('historical_snapshot') else 'Current dependency check required before reuse'}",
        "",
        "## Evidence-status overview (not a compliance score)",
        "",
        "| Status | Number |",
        "|---|---:|",
    ]
    for name in ("supported", "partial", "not_found", "needs_review", "possibly_not_applicable"):
        out.append(f"| {name} | {assessment['status_counts'].get(name, 0)} |")
    if assessment.get("sections"):
        out += ["", "## Execution and checkpoint status", "",
                "| Requirement | Execution | Last checkpoint | Finding revision | Audit |", "|---|---|---|---:|---|"]
        notes = []
        for key, section in assessment["sections"].items():
            out.append(f"| {clean(key)} | {section['execution_status']} | {section['checkpoint']} | {section['revision']} | {section['audit_status']} |")
            if section.get("stale_reasons") or section.get("failure_reason"):
                notes.append(f"- {clean(key)}: {clean(section.get('failure_reason') or ', '.join(section['stale_reasons']))}")
        if notes:
            out += ["", *notes]
    out += ["", "## Requirement-by-requirement evidence mapping", ""]
    for row in rows:
        req, f = row["requirement"], row["finding"]
        locations = {p["id"]: p for p in row["retrieved_evidence"]}
        out += [
            f"### {req['id']} — {clean(req['provision'])}", "",
            f"**Requirement (draft):** {clean(req['requirement'])}", "",
            f"**Legal source:** `{req['legal_source']}`, PDF page {req['legal_page']}, "
            f"chunk `{req['legal_source_chunk_id']}`; SHA-256 `{req['legal_sha256']}`", "",
            f"**Source quote:** “{clean(req['exact_quote'])}”", "",
            f"**Draft applicability:** {clean(req['applies_to'])}", "",
            f"**Evidence status:** `{f['status']}`", "",
            f"**Audit:** {row.get('audit_status', 'legacy / unspecified — not newly verified')}", "",
            f"**Assessment:** {clean(f['explanation'])}", "",
            f"**Applicability uncertainty:** {clean(f['applicability_reason'])}", "",
            "**Cited device evidence:**",
        ]
        if not f["evidence_ids"]:
            out.append("- None verified in retrieved results")
        for id_ in f["evidence_ids"]:
            p = locations.get(id_)
            if p is None:
                out.append(f"- `{clean(id_)}` — UNVERIFIED: missing from the saved retrieved evidence")
                continue
            locator = f"PDF page {p['page']}" if p["page"] else f"text block {p['block']}"
            out.append(f"- `{id_}` — `{p['source']}`, {locator}; SHA-256 `{p['sha256']}`")
        out += ["", "**Missing information / questions to investigate:**"]
        out += [f"- {clean(x)}" for x in f["missing_information"]] or ["- None identified in this partial review"]
        out += ["", "**Proposed actions for expert assessment:**"]
        out += [f"- {clean(x)}" for x in f["recommended_actions"]] or ["- Obtain specialist assessment"]
        out.append("")
    out += ["## Extraction and analysis limitations", ""]
    for item in assessment["limitations"]:
        out.append(f"- {item}")
    for page in assessment.get("unreadable_selected_pages", []):
        out.append(f"- Selected legal PDF page {page} had no extractable text")
    if assessment.get("rejected_unverifiable_quotes"):
        out.append(f"- {len(assessment['rejected_unverifiable_quotes'])} extracted requirements discarded for unverifiable quotes")
    out += ["", "**Mandatory human review:** confirm the legal version, all required provisions, device applicability, exact source text, and supporting device evidence."]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(out) + "\n", encoding="utf-8")
