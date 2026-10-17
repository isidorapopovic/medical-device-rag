"""Compatibility adapters: draft research and approved law never share authority."""
from datetime import date

from .ingestion import IngestionStore, records_from_manifest
from .regulatory_registry import RegistryStore, RegistryNotReady, digest


def review_register(app, *, edition_id=None, as_of=None, saved_scope=None) -> dict:
    binding = (saved_scope or {}).get("registry_selection")
    if binding:
        if edition_id and edition_id != binding["edition_id"]:
            raise ValueError("Registry edition changed; use a new assessment ID")
        edition_id = edition_id or binding["edition_id"]
        as_of = as_of or binding["as_of"]
    if edition_id is None:
        if as_of is not None:
            raise ValueError("Registry as-of date requires an edition")
        return app.load_json(app.STATE / "requirements_draft.json")
    if as_of is None:
        raise ValueError("Approved-law review requires an explicit registry as-of date")
    as_of = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    archive = IngestionStore(app.STATE / "ingestion")
    with RegistryStore(app.STATE / "regulatory_registry", archive) as registry:
        selected = registry.select(edition_id, as_of)
    edition = selected["edition"]
    manifest = archive.load(edition.manifest_sha256)
    records = {r["meta"]["source_span_id"]: r for r in records_from_manifest(manifest)}
    from .applicability_service import ApplicabilityStore
    rule_store = ApplicabilityStore(app.STATE / "applicability", archive)
    rule_bindings = {p.id: rule_store.binding(edition.id, p.id) for p in selected["requirements"]}
    requirements = []
    for provision in selected["requirements"]:
        record = records[provision.source_span_id]
        requirements.append(dict(id=provision.id, requirement=provision.exact_quote,
            exact_quote=provision.exact_quote, provision="/".join(provision.section_path),
            applies_to="unspecified", legal_source_chunk_id=record["id"],
            legal_source=record["meta"]["source"], legal_page=record["meta"]["page"],
            legal_sha256=edition.file_sha256, legal_quote_start=provision.start,
            legal_quote_end=provision.end, legal_quote_verified=True,
            human_validated=True, registry_edition_id=edition.id,
            registry_revision=selected["revision"], registry_as_of=as_of.isoformat(),
            applicability_rule_binding=rule_bindings[provision.id], registry_dependencies=provision.dependencies,
            evidence_type_tags=provision.evidence_type_tags))
    selection = {"edition_id": edition.id, "as_of": as_of.isoformat(),
                 "revision": selected["revision"], "project_id": archive.project_id,
                 "requirement_ids": [r["id"] for r in requirements],
                 "coverage": selected["coverage"], "applicability_rule_bindings": rule_bindings,
                 "selection_sha256": digest([edition.model_dump(mode="json"),
                    [r.model_dump(mode="json") for r in selected["requirements"]]])}
    return {"requirements": requirements, "source": "legal/" + manifest.document.original_name,
            "source_sha256": edition.file_sha256, "legal_version_label": edition.label,
            "selected_pdf_pages": sorted({r["legal_page"] for r in requirements if r["legal_page"]}),
            "unreadable_selected_pages": [], "rejected_unverifiable_quotes": [],
            "registry_selection": selection}


def report_registry_policy(scope: dict, requirement_ids, *, historical=False) -> dict:
    binding = scope.get("registry_selection")
    if not binding:
        return {"mode": "draft_research_only", "ready_for_authoritative_applicability": False,
                "coverage_status": "partial registry coverage", "warning": "legal_registry_not_ready"}
    if historical:
        return {"mode": "historical_registry_snapshot", "ready_for_authoritative_applicability": False,
                "coverage_status": "partial registry coverage", "warning": "historical_law_not_revalidated",
                "frozen_selection": binding}
    from . import pipeline as app
    current = review_register(app, edition_id=binding["edition_id"], as_of=binding["as_of"])
    current_binding = current["registry_selection"]
    if (binding != current_binding or not set(requirement_ids) <= set(current_binding["requirement_ids"])):
        raise RegistryNotReady()
    return {"mode": "approved_registry_scope", "ready_for_authoritative_applicability": True,
            "coverage_status": current_binding["coverage"]["coverage_status"],
            "coverage": current_binding["coverage"],
            "warning": "human_approved_as_of_date_not_automatic_latest_law"}
