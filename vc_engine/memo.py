"""Deterministic, evidence-linked research bundles with fail-closed citations."""
import json
import re
from copy import deepcopy
from html import escape
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from .comparables import compare
from .database import connect
from .evidence_gaps import evidence_gaps
from .investment_comparables import InvestmentFilters, query_investments
from .models import DEFAULT_DB, ROOT
from .regulatory_models import DEFAULT_FDA_DB, WARNINGS, utc_now
from .regulatory_store import FDAStore
from .scoring import scorecard
from .startup_profile import PROFILE_FIELDS, StartupProfile, profile_payload

SECTIONS = ("Company overview", "Clinical problem", "Analogous cleared devices", "Competitive differentiation",
            "Clinical evidence", "Regulatory considerations", "Investor/funding comparables", "Diligence questions and risks")
KINDS = {"startup_claim", "public_source_fact", "model_inference", "analyst_assessment"}


def source_registry(profile: StartupProfile, *, db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB) -> dict:
    registry = {"startup:" + (profile.input_sha256 or profile.fingerprint): dict(kind="startup_claim",
        label="Structured startup profile", fields={key: getattr(profile, key) for key in PROFILE_FIELDS},
        filename="startup_profile.json", row_number=None, source_url=None)}
    for source in profile.sources:
        registry["profile-source:" + source.source_id] = dict(kind="startup_claim", label=source.source_id,
            text=source.text, fields={}, page=source.page, chunk=source.chunk, source_url=source.source_url,
            filename=source.chunk or source.source_id, origin=source.origin)
    if Path(db).exists():
        with closing(connect(db, readonly=True)) as conn:
            for row in conn.execute("SELECT * FROM source_rows"):
                registry[row["id"]] = dict(kind="public_source_fact", label=row["input_filename"],
                    fields=json.loads(row["raw_json"]), filename=row["input_filename"], row_number=row["row_number"],
                    file_sha256=row["file_sha256"], source_url=None, status="CSV-reported, not independently verified")
    if Path(fda_db).exists():
        with FDAStore(fda_db, readonly=True) as store:
            for row in store.records():
                raw = json.loads(row["raw_json"])
                if raw.get("k_number") != row["k_number"]:
                    continue
                registry["fda:" + row["k_number"]] = dict(kind="public_source_fact", label=row["k_number"], fields=raw,
                    source_url=row["source_url"], source_checked_at=row["checked_at"], status="cached_official_record")
    return registry


def citation(source_id: str, field: str, quote: str) -> dict:
    return dict(source_id=source_id, field=field, quote=quote)


def audit_claims(claims: list[dict], sources: dict) -> tuple[list[dict], dict]:
    """Only literal source-field/quote membership, not semantic entailment."""
    if not isinstance(claims, list) or not isinstance(sources, dict):
        raise ValueError("Citation audit needs a claims list and source registry object")
    result, checked, valid, withheld = [], 0, 0, 0
    for original in claims:
        item = dict(original) if isinstance(original, dict) else {}
        references = item.get("citations", [])
        accepted, bad = [], False
        if item.get("kind") not in KINDS or not isinstance(references, list):
            bad, references = True, []
        for ref in references:
            checked += 1
            identifier = ref.get("source_id") if isinstance(ref, dict) else None
            source = sources.get(identifier) if isinstance(identifier, str) else None
            quote = ref.get("quote") if isinstance(ref, dict) else None
            field = ref.get("field") if isinstance(ref, dict) else None
            fields = source.get("fields", {}) if isinstance(source, dict) else {}
            text = fields.get(field) if isinstance(fields, dict) and isinstance(field, str) else None
            if isinstance(source, dict) and field == "text":
                text = source.get("text")
            if isinstance(quote, str) and quote and isinstance(text, str) and quote in text:
                valid += 1
                accepted.append(ref)
            else:
                bad = True
        if not accepted and item.get("status") not in {"unknown", "unverified", "needs_review", "not_found_in_index"}:
            bad = True
        item["citations"] = accepted
        if bad:
            withheld += 1
            item.update(text="Claim withheld: citation or evidence status needs review.", status="needs_review", citations=[],
                        kind=item.get("kind") if item.get("kind") in KINDS else "analyst_assessment")
        result.append(item)
    return result, dict(citations_checked=checked, valid_citations=valid, citation_validity=valid / checked if checked else None,
                       claims_withheld=withheld, limitation="Structural/literal validity only; not semantic, clinical or financial verification.")


def _claim(section, text, kind="analyst_assessment", status="unknown", refs=()):
    return dict(section=section, text=text, kind=kind, status=status, citations=list(refs))


def _anchors(items: list[dict] | tuple[dict, ...], sources: dict) -> list[dict]:
    result = []
    for anchor in items:
        identifier = anchor.get("source_id")
        if identifier not in sources and "profile-source:" + str(identifier) in sources:
            identifier = "profile-source:" + str(identifier)
        field = anchor.get("field", "text")
        quote = anchor.get("quote")
        if isinstance(quote, str) and quote:
            result.append(citation(identifier, field, quote))
    return result


def build_research(profile: StartupProfile, *, db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB, top_k=5,
                   scoring_config=None, scoring_enabled=False) -> dict:
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("Memo top_k must be 1–20 per candidate kind")
    comparison = compare(profile, db=db, fda_db=fda_db, top_k=100)
    selected = tuple(row for kind in ("company", "fda_510k_record") for row in
                     [item for item in comparison.results if item.kind == kind][:top_k])
    comparison = replace(comparison, results=selected,
        candidate_counts={**comparison.candidate_counts, "returned": len(selected)})
    gaps = evidence_gaps(profile, db=db)
    identifiers = {item.source_id for item in selected if item.kind == "company"}
    if Path(db).exists():
        with closing(connect(db, readonly=True)) as connection:
            if profile.name:
                identifiers.update(row[0] for row in connection.execute("SELECT id FROM companies WHERE name_key=?", (profile.name.casefold(),)))
        investments = asdict(query_investments(db=db, filters=InvestmentFilters(limit=1000), company_ids=identifiers))
    else:
        investments = dict(results=[], total_matching=0, limitations=["Local company/investment index missing"])
    sources = source_registry(profile, db=db, fda_db=fda_db)
    profile_id = "startup:" + (profile.input_sha256 or profile.fingerprint)
    claims = []
    for section, fields in ((SECTIONS[0], ("name", "device_name", "device_description")),
                            (SECTIONS[1], ("intended_use", "clinical_indication", "patient_population", "input_modality", "target_user", "workflow"))):
        for field in fields:
            value = getattr(profile, field)
            refs = [citation(profile_id, field, value)] if value else []
            refs.extend(citation("profile-source:" + anchor.source_id, "text", anchor.quote)
                        for anchor in profile.field_evidence if anchor.field == field)
            claims.append(_claim(section, f"Startup declares {field}: {value}" if value else f"{field}: unknown in the supplied startup profile.",
                "startup_claim", "unverified" if value else "unknown", refs))
    for row in selected:
        if row.kind == "fda_510k_record":
            sid = "fda:" + row.source_id
            refs = [citation(sid, "k_number", row.source_id)]
            raw = sources.get(sid, {}).get("fields", {})
            if isinstance(raw.get("device_name"), str):
                refs.append(citation(sid, "device_name", raw["device_name"]))
            description = row.regulatory.get("decision_description")
            if description:
                refs.append(citation(sid, "decision_description", description))
            claims.append(_claim(SECTIONS[2], f"Cached FDA record {row.source_id} reports {row.name!r}; decision: {description or 'unknown'}. Intended-use equivalence is not established.",
                                 "public_source_fact", "cached", refs))
        else:
            refs = _anchors(tuple(anchor for field in row.fields for anchor in field.evidence), sources)
            claims.append(_claim(SECTIONS[3], f"CSV-reported comparable {row.name}: lexical score {row.score:g}, observed feature coverage {row.coverage:.0%}; differentiation is not established.",
                                 "model_inference", "unverified", refs))
    if not any(row.kind == "fda_510k_record" for row in selected):
        claims.append(_claim(SECTIONS[2], "No eligible FDA record was returned from the inspected local cache; this is not an exhaustive FDA search."))
    if not any(row.kind == "company" for row in selected):
        claims.append(_claim(SECTIONS[3], "No eligible company comparable was returned from this bounded local search; differentiation remains unknown."))
    for gap in gaps.gaps:
        claims.append(_claim(SECTIONS[4] if gap.category not in {"regulatory_documentation", "intended_use_details"} else SECTIONS[5],
            gap.statement, "analyst_assessment", gap.status if gap.status in {"not_found_in_index", "needs_review"} else "unverified",
            _anchors(gap.evidence, sources)))
        claims.append(_claim(SECTIONS[7], f"Diligence: review {gap.category.replace('_', ' ')}; local source status is {gap.status}.",
                             "analyst_assessment", "unverified", _anchors(gap.evidence, sources)))
    for warning in WARNINGS:
        claims.append(_claim(SECTIONS[5], warning, "analyst_assessment", "unverified"))
    funding_table = []
    for row in investments["results"]:
        claim_id = "investment:" + row["investment_id"]
        claims.append({**_claim(SECTIONS[6], f"CSV reports relationship: {row['investor']} and {row['company']}; reported stage: {row['stage'] or 'unknown'}. All amounts remain separately attributed and unverified.",
            "public_source_fact", "claimed_only", _anchors(row["field_provenance"], sources)), "claim_id": claim_id})
        funding_table.append(dict(claim_id=claim_id, company=row["company"], investor=row["investor"],
            round_stage=row["stage"], round_date=row["round_date_as_reported"], evidence_status="claimed_only",
            round_amount={**row["reported_total_round_amount"], "amount_type": row["amount_type"]},
            individual_check={**row["individual_fund_check"], "amount_type": "individual_fund_check"},
            cumulative_funding={**row["company_cumulative_funding"], "amount_type": "company_cumulative_reported"},
            evidence_ids=list(dict.fromkeys(anchor["source_id"] for anchor in row["field_provenance"])),
            missing_data=row["missing_data"], join_status=row["join_status"]))
    if not funding_table:
        claims.append(_claim(SECTIONS[6], "No investment relationship matched the startup or returned comparable-company IDs in the local investment index; no investor participation or check is inferred."))
    claims, audit = audit_claims(claims, sources)
    memo = dict(schema_version=1, generated_at=utc_now(), generation_mode="deterministic_offline", profile_fingerprint=profile.fingerprint,
        profile_review_status=profile.review_status, title="MedTech VC research memo", sections=list(SECTIONS), claims=claims,
        funding_table=funding_table, sources=sources, citation_audit=audit,
        limitations=["Research only; not an investment recommendation or forecast. Review/edit the startup profile before relying on matches.",
                     "CSV claims and cached FDA records have not been independently rechecked; clinical/financial equivalence is not established.",
                     "No LLM, Ollama, network or automatic public-document download is used. Empty gaps describe this local index only."])
    return dict(memo=memo, comparables=asdict(comparison), evidence_gaps=asdict(gaps), investments=investments,
                scorecard=scorecard(scoring_config, source_ids=set(sources), enabled=scoring_enabled), profile=profile_payload(profile))


def render_markdown(memo: dict) -> str:
    claims, audit = audit_claims(memo["claims"], memo["sources"])
    lines = ["# MedTech VC research memo", "", f"Profile review: **{memo['profile_review_status']}**. Deterministic offline research; no investment prediction.", ""]
    for section in SECTIONS:
        lines.extend(["## " + section, ""])
        for item in claims:
            if item.get("section") != section:
                continue
            references = ", ".join("[" + escape(identifier) + "]" for identifier in dict.fromkeys(ref["source_id"] for ref in item["citations"]))
            # Escaped source text is data; never emit raw HTML from decks/CSVs.
            text = escape(str(item["text"])).replace("\n", " ")
            lines.append(f"- **{item['kind']} / {item['status']}**: {text}" + (" Sources: " + references if references else ""))
        if section == SECTIONS[6] and memo["funding_table"]:
            lines += ["", "| Company / investor | Reported round | Individual check | Company cumulative funding |", "| --- | --- | --- | --- |"]
            valid_rows = {claim.get("claim_id") for claim in claims if claim["status"] != "needs_review"}
            for row in memo["funding_table"]:
                if row["claim_id"] not in valid_rows:
                    continue
                def amount(item):
                    value = f"{item['currency'] or 'currency unknown'} {item['amount']:g}" if item["amount"] is not None else "unknown"
                    return escape(f"{value}; type: {item['amount_type'] or 'unknown'}; source: {item['source_url'] or 'unknown'}; as of: {item['as_of_date'] or 'unknown'}").replace("|", "\\|").replace("\n", " ")
                lines.append("| " + escape(row["company"] + " / " + row["investor"]).replace("|", "\\|").replace("\n", " ") + " | " + " | ".join(amount(row[key]) for key in ("round_amount", "individual_check", "cumulative_funding")) + " |")
        lines.append("")
    lines.extend(["## Sources", ""])
    used = {ref["source_id"] for claim in claims for ref in claim["citations"]}
    for identifier in sorted(used):
        source = memo["sources"][identifier]
        locator = source.get("filename", source["label"])
        if source.get("row_number"):
            locator += f" row {source['row_number']}"
        if source.get("page"):
            locator += f" page {source['page']}"
        lines.append(f"- [{escape(identifier)}]: {escape(locator)}; {escape(source.get('source_url') or 'local source')}")
    lines += ["", *memo["limitations"], "", "Citation checks establish literal reference validity, not semantic verification."]
    return "\n".join(lines) + "\n"


def export_research(bundle: dict, *, root: str | Path = ROOT / "reports/vc") -> Path:
    bundle = deepcopy(bundle)
    memo = bundle["memo"]
    memo["claims"], memo["citation_audit"] = audit_claims(memo["claims"], memo["sources"])
    valid_rows = {claim.get("claim_id") for claim in memo["claims"] if claim["status"] != "needs_review"}
    memo["funding_table"] = [row for row in memo["funding_table"] if row["claim_id"] in valid_rows]
    root = Path(root).resolve()
    name = bundle["profile"].get("name") or "unknown"
    slug = re.sub(r"[^a-z0-9-]+", "-", name.casefold()).strip("-")[:40] or "startup"
    identifier = "profile-" + slug + "-" + bundle["memo"]["profile_fingerprint"][:8] + "-" + uuid4().hex[:12]
    destination = root / identifier
    destination.mkdir(parents=True, exist_ok=False)
    payloads = {"memo.json": bundle["memo"], "comparables.json": bundle["comparables"],
                "scorecard.json": bundle["scorecard"], "evidence_gaps.json": bundle["evidence_gaps"], "startup_profile.json": bundle["profile"]}
    for filename, payload in payloads.items():
        with (destination / filename).open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
    with (destination / "memo.md").open("x", encoding="utf-8") as stream:
        stream.write(render_markdown(bundle["memo"]))
    return destination
