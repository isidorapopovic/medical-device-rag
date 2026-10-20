"""Run with python -m vc_engine; requires only the Python standard library."""
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
    parser = argparse.ArgumentParser(description="Offline MedTech VC CSV data (no independent verification)",
        epilog="Examples: python -m vc_engine ingest; python -m vc_engine stats; "
               "python -m vc_engine search --query cardiology --country Germany")
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
    args = parser.parse_args(argv)
    try:
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
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
