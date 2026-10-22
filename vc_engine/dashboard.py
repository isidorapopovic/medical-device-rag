"""Local VC Research Streamlit screens, separated from the MDR workspace."""
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from .database import connect
from .evaluation import DEFAULT_GOLD, evaluate_labels
from .investment_comparables import InvestmentFilters, query_investments
from .memo import build_research, export_research, render_markdown
from .models import DEFAULT_DB, QueryFilters, ROOT
from .queries import provenance, search_companies
from .regulatory_models import DEFAULT_FDA_DB
from .startup_profile import profile_from_dict, profile_payload
from .startup_uploads import ingest_startup_upload
from .terms import load_terms, lookup_term


def company_explorer(db=DEFAULT_DB):
    st.subheader("Company explorer")
    if not Path(db).exists():
        st.info("Import the company/investment/document CSVs with python -m vc_engine ingest to browse local data.")
        return
    keyword = st.text_input("Search companies", key="vc_company_query")
    country = st.text_input("Headquarters country (exact)", key="vc_country")
    category = st.text_input("Clinical category (exact)", key="vc_category")
    with closing(connect(db, readonly=True)) as connection:
        catalog_ids = {row[0] for row in connection.execute("""SELECT DISTINCT c.entity_id FROM source_claims c
            JOIN source_rows r ON r.id=c.source_row_id WHERE c.entity_table='companies' AND r.dataset='companies'""")}
        companies = [item for item in search_companies(connection, QueryFilters(country=country, clinical_category=category,
            keyword=keyword, limit=1000)) if item.id in catalog_ids]
        st.caption(f"{len(companies)} company-catalog records. Investment-only placeholders are excluded from this explorer.")
        st.dataframe([dict(company=item.name, country=item.country or "Unknown", clinical_use_case=item.clinical_use_case or "Unknown",
            total_funding=item.total_funding_amount, currency=item.total_funding_currency or "Unknown", revenue=item.revenue_amount,
            evidence_status="CSV claim; not independently verified") for item in companies], hide_index=True)
        if companies:
            selected = st.selectbox("Company details", companies, format_func=lambda item: item.name, key="vc_selected_company")
            st.warning("Regulatory statements in the CSV are claims. No product-specific clearance or CE finding is established for the company.")
            st.json(asdict(selected))
            with st.expander("Source rows, URLs and missing values"):
                st.json(provenance(connection, "companies", selected.id))
            st.write("Related reported investor relationships")
            st.json(asdict(query_investments(db=db, filters=InvestmentFilters(company=selected.name))))
    with st.expander("VC glossary"):
        terms = load_terms()
        term = st.selectbox("Explain a VC term", [item.id for item in terms], key="vc_term")
        st.json(asdict(lookup_term(term)))
        st.caption("Educational draft glossary; definitions and formulas require expert review.")


def startup_evaluator(db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB):
    st.subheader("Startup evaluator")
    st.caption("Enter/edit JSON or load a local PDF/DOCX deck. Extraction uses explicit labels only; every claim needs review.")
    upload = st.file_uploader("Startup JSON or pitch deck (20 MiB maximum)", type=["json", "pdf", "docx"], key="vc_upload")
    if st.button("Load local startup upload", disabled=upload is None):
        result = ingest_startup_upload(upload.name, upload.getvalue())
        st.session_state["vc_editor"] = json.dumps(profile_payload(result["profile"]), indent=2)
        st.session_state["vc_profile_text"] = st.session_state["vc_editor"]
        st.session_state.pop("vc_bundle", None)
        st.session_state.pop("vc_profile", None)
        st.session_state["vc_review_confirmed"] = False
        st.info("Stored locally; extraction status: " + result["status"])
        for warning in result["warnings"]:
            st.warning(warning)
    if "vc_editor" not in st.session_state:
        st.session_state["vc_editor"] = st.session_state.get("vc_profile_text",
            (ROOT / "docs/vc/startup_profile.example.json").read_text(encoding="utf-8"))
    def changed_profile():
        st.session_state["vc_profile_text"] = st.session_state["vc_editor"]
        st.session_state["vc_review_confirmed"] = False
    text = st.text_area("Editable startup profile JSON", height=350, key="vc_editor", max_chars=2 * 1024 * 1024,
                        on_change=changed_profile)
    st.session_state["vc_profile_text"] = text
    reviewer = st.text_input("Reviewer name", key="vc_reviewer")
    confirmed = st.checkbox("I reviewed and edited the startup fields and source claims", key="vc_review_confirmed")
    if st.button("Evaluate startup offline", type="primary"):
        if confirmed and not reviewer.strip():
            raise ValueError("Enter your reviewer name to record a profile review")
        profile = profile_from_dict(json.loads(text), reviewer=reviewer if confirmed else None)
        bundle = build_research(profile, db=db, fda_db=fda_db)
        st.session_state["vc_profile"] = profile_payload(profile)
        st.session_state["vc_bundle"] = bundle
    bundle = st.session_state.get("vc_bundle")
    if not bundle:
        return
    st.caption("Results refer to the last evaluated profile. Re-evaluate after editing fields.")
    st.warning("Profile review: " + bundle["memo"]["profile_review_status"] + ". Lexical scores are unvalidated research heuristics.")
    for kind, label in (("fda_510k_record", "Comparable FDA 510(k) records (cached)"), ("company", "Comparable company claims")):
        st.write(label)
        rows = [row for row in bundle["comparables"]["results"] if row["kind"] == kind]
        st.dataframe([dict(name=row["name"], source_id=row["source_id"], score=row["score"], coverage=row["coverage"],
                           confidence=row["confidence"], evidence_status=row["evidence_status"]) for row in rows], hide_index=True)
        with st.expander(label + " — field evidence and limitations"):
            st.json(rows)
    st.write("Startup claims and source/page anchors")
    st.json(bundle["profile"])
    st.write("Evidence gaps")
    st.dataframe([dict(category=gap["category"], status=gap["status"], finding=gap["statement"]) for gap in bundle["evidence_gaps"]["gaps"]], hide_index=True)
    with st.expander("Investment relationships and source audit"):
        st.json(bundle["investments"])


def research_memo(db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB):
    st.subheader("Research memo")
    if "vc_profile" not in st.session_state:
        st.info("Evaluate a startup first. Memo generation is deterministic and works without Ollama.")
        return
    enabled = st.checkbox("Enable manual analyst screening rubric", value=False, key="vc_scoring_enabled")
    if enabled:
        st.warning("Only explicitly human-verified, reviewed ratings with known source IDs are eligible. Missing criteria remain unrated.")
        scoring = st.text_area("Analyst rubric JSON", value='{"ratings": {}}', key="vc_scoring_json", height=170)
        with st.expander("Available evidence IDs for manual review"):
            st.write(list(st.session_state.get("vc_bundle", {}).get("memo", {}).get("sources", {})))
    if st.button("Generate research memo", type="primary"):
        profile = profile_from_dict(st.session_state["vc_profile"])
        bundle = build_research(profile, db=db, fda_db=fda_db, scoring_config=json.loads(scoring) if enabled else None, scoring_enabled=enabled)
        st.session_state["vc_bundle"] = bundle
    bundle = st.session_state.get("vc_bundle")
    if not bundle:
        return
    card = bundle["scorecard"]
    st.metric("Human-rated rubric coverage", f"{card['coverage']:.0%}")
    st.caption("Scoring in this generated bundle: " + ("enabled" if card["enabled"] else "disabled") + ". Regenerate after changing the rubric or toggle.")
    st.caption(f"Rated weight {card['rated_weight']:g} / total {card['total_weight']:g}; minimum coverage {card['minimum_coverage']:.0%}.")
    st.metric("Mean over rated criteria (0–5)", f"{card['rated_mean_0_to_5']:.2f}" if card["rated_mean_0_to_5"] is not None else "Unrated")
    st.metric("Screening score (coverage guard)", f"{card['screening_score_0_to_5']:.2f}" if card["screening_score_0_to_5"] is not None else "Withheld")
    st.warning(card["warning"])
    st.dataframe(card["criteria"], hide_index=True)
    st.bar_chart({"rated weight": [card["rated_weight"]], "unrated weight": [1 - card["rated_weight"]]})
    st.markdown(render_markdown(bundle["memo"]))
    st.download_button("Download memo Markdown", render_markdown(bundle["memo"]), file_name="memo.md", mime="text/markdown")
    st.download_button("Download memo JSON", json.dumps(bundle["memo"], ensure_ascii=False, indent=2), file_name="memo.json", mime="application/json")
    if st.button("Export research bundle locally"):
        destination = export_research(bundle)
        st.success("Saved a new local report folder: " + destination.name)


def evaluation_screen(db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB):
    st.subheader("Evaluation")
    st.info("Use independent human annotations. Empty templates show no fabricated accuracy or ground truth.")
    upload = st.file_uploader("Human-annotated comparable labels JSON (4 MiB maximum)", type=["json"], key="vc_gold_upload")
    if st.button("Evaluate human labels"):
        if upload:
            content = upload.getvalue()
            if len(content) > 4 * 1024 * 1024:
                raise ValueError("Evaluation labels exceed 4 MiB")
            payload = json.loads(content.decode("utf-8-sig"))
        else:
            payload = json.loads(DEFAULT_GOLD.read_text(encoding="utf-8"))
        result = evaluate_labels(payload, db=db, fda_db=fda_db, memo=st.session_state.get("vc_bundle", {}).get("memo"))
        st.session_state["vc_evaluation"] = result
    if "vc_evaluation" in st.session_state:
        result = st.session_state["vc_evaluation"]
        st.json(result)
        measured = {key: result[key] for key in ("recall_at_5", "precision_at_5", "extraction_field_accuracy") if result.get(key) is not None}
        if measured:
            st.bar_chart({key: [value] for key, value in measured.items()})


def render_vc_research(*, db=DEFAULT_DB, fda_db=DEFAULT_FDA_DB):
    st.title("VC Research")
    st.caption("Local MedTech research • CSV claims • cached FDA 510(k) records • source-linked diligence")
    st.warning("No authentication: keep this app bound to localhost. Do not expose confidential decks externally. No automatic downloads or third-party uploads.")
    view = st.radio("VC view", ["Company explorer", "Startup evaluator", "Research memo", "Evaluation"], horizontal=True, key="vc_view")
    try:
        if view == "Company explorer":
            company_explorer(db)
        elif view == "Startup evaluator":
            startup_evaluator(db, fda_db)
        elif view == "Research memo":
            research_memo(db, fda_db)
        else:
            evaluation_screen(db, fda_db)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        st.error("VC research could not complete: " + str(exc))
