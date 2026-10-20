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
    args = parser.parse_args(argv)
    try:
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
