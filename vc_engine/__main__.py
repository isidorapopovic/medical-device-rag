"""Run with python -m vc_engine; HTTP dependencies load only for opt-in FDA requests."""
import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from .database import connect
from .ingest import ingest
from .models import DEFAULT_DB, DEFAULT_FILES, DEFAULT_REPORT, QueryFilters
from .queries import search_companies, search_documents, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local MedTech VC data and FDA 510(k) research (network opt-in)",
        epilog="Examples: python -m vc_engine ingest; python -m vc_engine stats; "
               "python -m vc_engine search --query cardiology --country Germany; "
               "python -m vc_engine fda-search --query echocardiography --online")
    commands = parser.add_subparsers(dest="command", required=True)
    loader = commands.add_parser("ingest", help="Import three CSVs transactionally; preserve source claims")
    for option, kind in (("companies", "companies"), ("investments", "investments"), ("documents", "source_documents")):
        loader.add_argument("--" + option, type=Path, default=DEFAULT_FILES[kind])
    loader.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Import quality JSON output path")
    summary = commands.add_parser("stats", help="Read record counts and unknown/unverified data counts")
    search = commands.add_parser("search", help="Literal keyword search; exact named filters (case insensitive)")
    search.add_argument("--query", dest="keyword")
    for option in ("country", "company", "investor", "stage"):
        search.add_argument("--" + option)
    search.add_argument("--clinical-category")
    search.add_argument("--limit", type=int, default=100)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--entity", choices=("companies", "documents"), default="companies")
    for command in (loader, summary, search):
        command.add_argument("--db", type=Path, default=DEFAULT_DB, help="Separate VC SQLite database path")
    from .regulatory_models import DEFAULT_FDA_DB
    fda_search = commands.add_parser("fda-search", help="Research-only FDA 510(k) matches; cached/offline by default")
    fda_import = commands.add_parser("fda-import", help="Fetch/cache an exact FDA K-number; offline by default")
    fda_search.add_argument("--query", help="Literal phrase in FDA device_name, not semantic intended-use search")
    fda_search.add_argument("--device-name", help="Exact device name")
    fda_search.add_argument("--applicant", help="Exact applicant/manufacturer name as reported")
    fda_search.add_argument("--product-code", help="Exact three-letter FDA product code")
    fda_search.add_argument("--limit", type=int, default=10)
    fda_import.add_argument("--k-number", required=True)
    for command in (fda_search, fda_import):
        command.add_argument("--fda-db", type=Path, default=DEFAULT_FDA_DB, help="Dedicated FDA cache, separate from VC and MDR")
        command.add_argument("--online", action="store_true", help="Explicitly allow bounded requests to api.fda.gov")
        command.add_argument("--refresh", action="store_true", help="Recheck live; requires --online, bypasses fresh cache")
        command.add_argument("--page-size", type=int, default=10)
        command.add_argument("--max-pages", type=int, default=5)
        command.add_argument("--max-records", type=int, default=100)
        command.add_argument("--timeout", type=float, default=15)
        command.add_argument("--retries", type=int, default=2)
        command.add_argument("--cache-hours", type=float, default=24)
    profile_command = commands.add_parser("profile", help="Normalize editable startup JSON; fields remain unverified")
    profile_command.add_argument("--input", type=Path, required=True)
    profile_command.add_argument("--output", type=Path, required=True)
    profile_command.add_argument("--reviewer", help="Record your review attestation after reviewing/editing all profile fields")
    compare_command = commands.add_parser("compare", help="Offline company/FDA-cache comparables with field evidence")
    gaps_command = commands.add_parser("evidence-gaps", help="Offline startup evidence inventory with source status")
    for command in (compare_command, gaps_command):
        command.add_argument("--profile", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--db", type=Path, default=DEFAULT_DB)
    compare_command.add_argument("--fda-db", type=Path, default=DEFAULT_FDA_DB)
    compare_command.add_argument("--top-k", type=int, default=5)
    compare_command.add_argument("--weights", type=Path, help="JSON object containing all five baseline feature weights, summing to 1")
    compare_command.add_argument("--scan-cap", type=int, default=10000)
    from .terms import DEFAULT_TERMS
    terms = commands.add_parser("terms", help="Human-editable educational VC glossary; formulas are not calculations")
    term_commands = terms.add_subparsers(dest="term_action", required=True)
    term_list = term_commands.add_parser("list")
    term_show = term_commands.add_parser("show")
    term_show.add_argument("term")
    term_search = term_commands.add_parser("search")
    term_search.add_argument("query")
    term_validate = term_commands.add_parser("validate")
    for command in (term_list, term_show, term_search, term_validate):
        command.add_argument("--registry", type=Path, default=DEFAULT_TERMS)
    investments = commands.add_parser("investment-comparables", help="Read-only reported investment relationships and conservative company joins")
    for name in ("specialty", "indication", "country", "investor-country", "stage", "product-category", "company", "investor", "keyword"):
        investments.add_argument("--" + name)
    investments.add_argument("--profile", type=Path, help="Restrict relationships to Task 03 comparable-company IDs")
    investments.add_argument("--top-k", type=int, default=5)
    investments.add_argument("--fda-db", type=Path, default=DEFAULT_FDA_DB)
    documents = commands.add_parser("vc-documents", help="Unverified document link catalog; never fetches content")
    for name in ("query", "fund", "priority", "source-id"):
        documents.add_argument("--" + name)
    for command in (investments, documents):
        command.add_argument("--db", type=Path, default=DEFAULT_DB)
        command.add_argument("--limit", type=int, default=100)
        command.add_argument("--offset", type=int, default=0)
    from .vc_documents import DEFAULT_DOWNLOADS
    fetch = commands.add_parser("vc-fetch-document", help="Separate explicit public-document download; never creates financial facts")
    fetch.add_argument("--source-id", required=True)
    fetch.add_argument("--db", type=Path, default=DEFAULT_DB)
    fetch.add_argument("--output-dir", type=Path, default=DEFAULT_DOWNLOADS)
    fetch.add_argument("--online", action="store_true")
    fetch.add_argument("--extract", action="store_true", help="Explicit local PDF/DOCX/TXT extraction, no OCR or indexing")
    fetch.add_argument("--timeout", type=float, default=15)
    fetch.add_argument("--max-bytes", type=int, default=20 * 1024 * 1024)
    args = parser.parse_args(argv)
    try:
        if args.command == "terms":
            from .terms import DISCLAIMER, load_terms, lookup_term, search_terms
            if args.term_action == "show":
                payload = {"term": asdict(lookup_term(args.term, path=args.registry)), "disclaimer": DISCLAIMER}
            elif args.term_action == "validate":
                payload = {"schema_version": 1, "valid": True, "terms_count": len(load_terms(args.registry)), "disclaimer": DISCLAIMER}
            else:
                payload = {"terms": [asdict(term) for term in search_terms(args.query if args.term_action == "search" else None, path=args.registry)], "disclaimer": DISCLAIMER}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "investment-comparables":
            from .investment_comparables import InvestmentFilters, query_investments
            identifiers, profile_report = None, None
            if args.profile:
                from .startup_profile import load_profile
                from .comparables import compare
                profile_report = compare(load_profile(args.profile), db=args.db, fda_db=args.fda_db, top_k=args.top_k)
                identifiers = {item.source_id for item in profile_report.results if item.kind == "company"}
            filters = InvestmentFilters(**{name: getattr(args, name) for name in InvestmentFilters.__dataclass_fields__})
            payload = asdict(query_investments(db=args.db, filters=filters, company_ids=identifiers))
            if profile_report:
                payload["profile_comparison"] = asdict(profile_report)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "vc-documents":
            from .vc_documents import query_catalog
            entries = query_catalog(db=args.db, keyword=args.query, fund=args.fund, priority=args.priority,
                                    source_id=args.source_id, limit=args.limit, offset=args.offset)
            print(json.dumps({"results": [asdict(item) for item in entries], "status": "unverified_link_catalog",
                              "limitations": ["No content fetched; expected fields are not extracted financial facts."]}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "vc-fetch-document":
            from .vc_documents import fetch_document
            result = fetch_document(args.source_id, db=args.db, output_dir=args.output_dir, online=args.online,
                                    extract=args.extract, timeout=args.timeout, max_bytes=args.max_bytes)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["download_status"] == "downloaded" and result["extraction_status"] not in {"failed", "needs_ocr"} else 1
        if args.command in {"profile", "compare", "evidence-gaps"}:
            from .ingest import write_report
            from .startup_profile import load_profile, profile_payload
            source = args.input if args.command == "profile" else args.profile
            protected = {source.resolve(), DEFAULT_DB.resolve(), DEFAULT_FDA_DB.resolve()}
            if args.command != "profile":
                protected.add(args.db.resolve())
            if args.command == "compare":
                protected.add(args.fda_db.resolve())
                if args.weights:
                    protected.add(args.weights.resolve())
            if args.output.resolve() in protected or args.output.suffix.lower() != ".json":
                raise ValueError("Output must be a separate .json report, not an input/configuration/database path")
            profile = load_profile(source, reviewer=args.reviewer if args.command == "profile" else None)
            if args.command == "profile":
                payload = profile_payload(profile)
            elif args.command == "compare":
                from .comparables import compare
                weights = json.loads(args.weights.read_text(encoding="utf-8-sig")) if args.weights else None
                payload = asdict(compare(profile, db=args.db, fda_db=args.fda_db, top_k=args.top_k,
                                         weights=weights, scan_cap=args.scan_cap))
            else:
                from .evidence_gaps import evidence_gaps
                payload = asdict(evidence_gaps(profile, db=args.db))
            write_report(args.output, payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command in {"fda-search", "fda-import"}:
            from .regulatory_models import FDAQuery, FetchLimits
            from .regulatory_search import search_precedents
            query = FDAQuery(k_number=args.k_number) if args.command == "fda-import" else FDAQuery(
                query=args.query, device_name=args.device_name, applicant=args.applicant, product_code=args.product_code)
            limits = FetchLimits(page_size=args.page_size, max_pages=args.max_pages, max_records=args.max_records,
                                timeout=args.timeout, retries=args.retries, cache_hours=args.cache_hours)
            result = search_precedents(query, db=args.fda_db, limit=1 if args.command == "fda-import" else args.limit,
                                      online=args.online, refresh=args.refresh, limits=limits)
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return 0
        if args.command == "ingest":
            result = ingest(companies=args.companies, investments=args.investments, documents=args.documents,
                            db=args.db, report_path=args.report)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["status"] == "completed_with_rejections" else 0
        connection = connect(args.db, readonly=True)
        try:
            if args.command == "stats":
                result = stats(connection)
            elif args.entity == "documents":
                if args.country or args.company or args.stage or args.clinical_category:
                    raise ValueError("Document search supports --query and --investor (exact fund name) only")
                result = [asdict(item) for item in search_documents(connection, keyword=args.keyword,
                    fund_name=args.investor, limit=args.limit, offset=args.offset)]
            else:
                filters = QueryFilters(**{field: getattr(args, field) for field in QueryFilters.__dataclass_fields__})
                result = [asdict(item) for item in search_companies(connection, filters)]
        finally:
            connection.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
