"""Strict CSV loading, deterministic upserts and field-level source provenance."""
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .database import connect, json_text, upsert
from .models import (DEFAULT_DB, DEFAULT_FILES, DEFAULT_REPORT, HEADERS, clean,
                     currency, iso_date, number, stable_id, year)


class ImportValidationError(ValueError):
    """Report is saved even when preflight fails; database is not changed."""


def money(value: str | None, explicit_currency: str | None = None) -> tuple[float | None, str | None]:
    """Accept explicit currency units; never guess currency from geography."""
    text = clean(value)
    code = currency(explicit_currency)
    scale = 1
    unit = re.fullmatch(r"([A-Za-z]{3})\s+(thousand|million|billion)", clean(explicit_currency) or "", re.IGNORECASE)
    if unit:
        code = currency(unit[1])
        scale = {"thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}[unit[2].lower()]
    if text:
        match = re.fullmatch(r"(?:([A-Za-z]{3})\s+)?([+-]?[\d,.]+)(?:\s+([A-Za-z]{3}))?", text)
        if match:
            embedded = currency(match[1] or match[3])
            if embedded and code and embedded != code:
                return None, code
            code = embedded or code
            parsed = number(match[2])
            amount = parsed * scale if parsed is not None and code else None
            return (amount if amount is not None and abs(amount) < float("inf") else None), code
    return None, code


def load_csv(kind: str, path: Path) -> tuple[list[dict], dict]:
    payload = path.read_bytes()
    fingerprint = hashlib.sha256(payload).hexdigest()
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
    headers = next(reader, [])
    missing = sorted(set(HEADERS[kind]) - set(headers))
    extra = sorted(set(headers) - set(HEADERS[kind]))
    duplicates = sorted(key for key, count in Counter(headers).items() if count > 1)
    if missing or extra or duplicates:
        raise ImportValidationError(
            f"{path.name}: invalid CSV columns; missing={missing}, unexpected={extra}, duplicate={duplicates}")
    rows = []
    while True:
        start_line = reader.line_num + 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        if not cells:
            continue
        raw = dict(zip(headers, cells))
        if len(cells) != len(headers):
            raw[None] = cells[len(headers):]
        rows.append({"raw": raw, "row_number": start_line, "end_line_number": reader.line_num})
    return rows, {"input_filename": path.name, "input_path": str(path.resolve()), "file_sha256": fingerprint}


def company_values(raw: dict) -> dict:
    name = clean(raw.get("company"))
    funding = number(raw.get("dealroom_reported_total_funding_usd_millions"))
    # Guard multiplication overflow; original million-denominated value remains in provenance.
    funding = funding * 1_000_000 if funding is not None and abs(funding) < 1e302 else None
    revenue, revenue_currency = money(raw.get("revenue_value"))
    return dict(id=stable_id("company", name), name=name, name_key=name.casefold(),
                country=clean(raw.get("headquarters_country")),
                clinical_category=clean(raw.get("clinical_category")),
                clinical_use_case=clean(raw.get("clinical_use_case")),
                founded_year=year(raw.get("founded_year")), total_funding_amount=funding,
                total_funding_currency="USD" if funding is not None else None,
                revenue_amount=revenue, revenue_currency=revenue_currency,
                revenue_year=year(raw.get("revenue_year")),
                clinical_study_url=clean(raw.get("clinical_evidence_study_url")),
                regulatory_status_as_reported=clean(raw.get("regulatory_status_as_reported")),
                observed_date=iso_date(raw.get("research_date")), raw_json=json_text(raw))


def persist_row(connection, kind: str, raw: dict, changes: Counter) -> list[tuple[str, str]]:
    """Return every entity to which this input row contributes claims."""
    if kind == "companies":
        values = company_values(raw)
        changes[f"companies.{upsert(connection, 'companies', values)}"] += 1
        return [(kind, values["id"])]
    if kind == "source_documents":
        source_id = clean(raw["source_id"])
        values = dict(id=stable_id("document", source_id), source_id=source_id.casefold(),
                      fund_name=clean(raw["fund_name"]), title=clean(raw["document_title"]),
                      document_type=clean(raw["document_type"]), year=year(raw["year"]),
                      format=clean(raw["format"]), url=clean(raw["direct_document_or_page_url"]),
                      landing_page=clean(raw["official_landing_page"]),
                      verification_as_reported=clean(raw["verification_status"]),
                      observed_date=iso_date(raw["observed_2026_10_16"]), raw_json=json_text(raw))
        changes[f"source_documents.{upsert(connection, kind, values)}"] += 1
        return [(kind, values["id"])]
    company_name, investor_name = clean(raw["company"]), clean(raw["investor"])
    company_id, investor_id = stable_id("company", company_name), stable_id("investor", investor_name)
    if not connection.execute("SELECT 1 FROM companies WHERE id=?", (company_id,)).fetchone():
        values = company_values({"company": raw["company"]})
        changes[f"companies.{upsert(connection, 'companies', values)}"] += 1
    investor = dict(id=investor_id, name=investor_name, name_key=investor_name.casefold(),
                    country=clean(raw["investor_country"]), investor_type=clean(raw["investor_type"]),
                    raw_json=json_text({key: raw[key] for key in ("investor", "investor_country", "investor_type")}))
    changes[f"investors.{upsert(connection, 'investors', investor)}"] += 1
    round_amount, round_currency = money(raw["reported_round_amount"], raw["reported_round_currency"])
    # A round's currency does not establish the currency of an individual check.
    check_amount, check_currency = money(raw["individual_fund_check_amount"])
    identity = [raw[key] for key in ("investor", "company", "investment_relationship", "round_stage",
                                   "round_date", "round_announcement_source", "fund_portfolio_source")]
    values = dict(id=stable_id("investment", *identity), company_id=company_id, investor_id=investor_id,
                  relationship=clean(raw["investment_relationship"]), stage=clean(raw["round_stage"]),
                  round_date=iso_date(raw["round_date"]), round_amount=round_amount,
                  round_currency=round_currency, amount_type=clean(raw["amount_type"]),
                  fund_check_amount=check_amount, fund_check_currency=check_currency,
                  verification_as_reported=clean(raw["verification_level"]),
                  observed_date=iso_date(raw["as_of_date"]), raw_json=json_text(raw))
    changes[f"investments.{upsert(connection, 'investments', values)}"] += 1
    return [(kind, values["id"]), ("investors", investor_id), ("companies", company_id)]


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="vc-quality-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def normalization_issues(kind: str, raw: dict) -> list[str]:
    parsers = {
        "companies": {"founded_year": year, "revenue_year": year, "research_date": iso_date,
                      "dealroom_reported_total_funding_usd_millions": number,
                      "revenue_value": lambda value: money(value)[0]},
        "investments": {"round_date": iso_date, "as_of_date": iso_date,
                        "reported_round_currency": lambda value: money("0", value)[1],
                        "reported_round_amount": lambda value: money(value, raw["reported_round_currency"])[0],
                        "individual_fund_check_amount": lambda value: money(value)[0]},
        "source_documents": {"year": year, "observed_2026_10_16": iso_date},
    }
    return [field for field, parse in parsers[kind].items() if clean(raw[field]) and parse(raw[field]) is None]


def ingest(*, companies: str | Path = DEFAULT_FILES["companies"],
           investments: str | Path = DEFAULT_FILES["investments"],
           documents: str | Path = DEFAULT_FILES["source_documents"],
           db: str | Path = DEFAULT_DB, report_path: str | Path = DEFAULT_REPORT) -> dict:
    from .queries import stats

    paths = {"companies": Path(companies), "investments": Path(investments), "source_documents": Path(documents)}
    report_path, db = Path(report_path), Path(db)
    # Report output must never overwrite a source or the database.
    if report_path.resolve() in {db.resolve(), *(path.resolve() for path in paths.values())}:
        raise ValueError("Report path must differ from CSV and database paths")
    if db.resolve() in {path.resolve() for path in paths.values()}:
        raise ValueError("Database path must differ from CSV paths")
    report = {"status": "preflight", "created_at": datetime.now(timezone.utc).isoformat(),
              "database": str(db.resolve()), "files": {}, "errors": [], "entity_changes": {},
              "provenance": {"table": "source_claims JOIN source_rows ON source_row_id=source_rows.id",
                             "row_numbers": "physical CSV start line, header is line 1; end line also stored",
                             "fields": "every input field, including blanks; original strings retained",
                             "independently_verified": False}}
    loaded = {}
    for kind, path in paths.items():
        summary = dict(rows_read=0, rows_imported=0, rows_rejected=0, missing_values={}, normalization_issues=[], errors=[])
        report["files"][kind] = summary
        try:
            rows, origin = load_csv(kind, path)
            loaded[kind] = (rows, origin)
            summary.update(origin, rows_read=len(rows))
        except (OSError, UnicodeError, csv.Error, ImportValidationError) as exc:
            message = f"{path}: {exc}"
            summary["errors"].append(message)
            report["errors"].append(message)
    if report["errors"]:
        report["status"] = "failed_preflight"
        write_report(report_path, report)
        raise ImportValidationError("; ".join(report["errors"]))
    try:
        connection = connect(db)
    except (OSError, ValueError, sqlite3.Error) as exc:
        report["status"] = "failed_database"
        report["errors"].append(str(exc))
        write_report(report_path, report)
        raise
    changes = Counter()
    try:
        with connection:
            for kind, (rows, origin) in loaded.items():
                summary = report["files"][kind]
                missing = Counter({field: 0 for field in HEADERS[kind]})
                for row in rows:
                    raw, line = row["raw"], row["row_number"]
                    required = {"companies": ("company",), "investments": ("company", "investor"),
                                "source_documents": ("source_id", "document_title")}[kind]
                    invalid = None in raw or any(value is None for value in raw.values())
                    if invalid or any(not clean(raw[field]) for field in required):
                        summary["rows_rejected"] += 1
                        summary["errors"].append({"row_number": line, "error": "Row width mismatch or missing required identity: " + ", ".join(required)})
                        continue
                    missing.update(field for field, value in raw.items() if clean(value) is None)
                    issues = normalization_issues(kind, raw)
                    if issues:
                        summary["normalization_issues"].append({"row_number": line, "fields": issues,
                            "reason": "Not normalized; original values retained (amounts need explicit currency)"})
                    entities = persist_row(connection, kind, raw, changes)
                    row_id = stable_id("source_row", kind, origin["input_path"], origin["file_sha256"], str(line))
                    upsert(connection, "source_rows", dict(id=row_id, dataset=kind, **origin,
                           row_number=line, end_line_number=row["end_line_number"], raw_json=json_text(raw)))
                    for table, entity_id in entities:
                        for field, value in raw.items():
                            connection.execute("""INSERT INTO source_claims
                                (entity_table,entity_id,source_row_id,field_name,raw_value,normalized_value)
                                VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                                (table, entity_id, row_id, field, value, clean(value)))
                    summary["rows_imported"] += 1
                summary["missing_values"] = dict(missing)
            report["entity_changes"] = {table: {action: changes[f"{table}.{action}"] for action in ("inserted", "updated", "unchanged")}
                                       for table in ("companies", "investors", "investments", "source_documents")}
            report["summary"] = stats(connection)
            report["status"] = "completed_with_rejections" if any(s["rows_rejected"] for s in report["files"].values()) else "completed"
    except (OSError, ValueError, sqlite3.Error) as exc:
        report["status"] = "failed_transaction"
        report["errors"].append(str(exc))
        # The connection context rolls back accepted rows on transaction failure.
        for summary in report["files"].values():
            summary["rows_imported"] = 0
        report["entity_changes"] = {}
        write_report(report_path, report)
        raise
    finally:
        connection.close()
    write_report(report_path, report)
    return report
