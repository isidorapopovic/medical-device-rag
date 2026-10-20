"""Typed, parameterized offline queries and runtime quality summaries."""
import sqlite3

from .database import TABLES
from .models import CompanyResult, DocumentResult, QueryFilters, clean


def stats(connection: sqlite3.Connection) -> dict:
    counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
    quality = {
        "unknown_clinical_study_url": connection.execute("SELECT COUNT(*) FROM companies WHERE clinical_study_url IS NULL").fetchone()[0],
        "unknown_revenue": connection.execute("SELECT COUNT(*) FROM companies WHERE revenue_amount IS NULL").fetchone()[0],
        "unverified_regulatory_status": connection.execute("SELECT COUNT(*) FROM companies WHERE regulatory_independently_verified=0").fetchone()[0],
        "missing_investment_round_amount": connection.execute("SELECT COUNT(*) FROM investments WHERE round_amount IS NULL").fetchone()[0],
    }
    return {"counts": counts, "data_quality": quality,
            "verification": "CSV-reported claims only; no independent source verification performed"}


def _paging(filters: QueryFilters) -> None:
    if type(filters.limit) is not int or not 1 <= filters.limit <= 10000:
        raise ValueError("limit must be an integer between 1 and 10000")
    if type(filters.offset) is not int or filters.offset < 0:
        raise ValueError("offset must be a nonnegative integer")


def search_companies(connection: sqlite3.Connection, filters: QueryFilters = QueryFilters()) -> list[CompanyResult]:
    """All filters are ANDed; investor and stage must match the same relationship.

    country means company headquarters; keyword is a literal Unicode substring.
    Returned relationships include all investments for each matched company.
    """
    _paging(filters)
    clauses, parameters = [], []
    for column, value in (("c.country", filters.country), ("c.clinical_category", filters.clinical_category),
                          ("c.name", filters.company)):
        if clean(value):
            clauses.append(f"casefold({column})=?")
            parameters.append(clean(value).casefold())
    relationships, relation_parameters = [], []
    for column, value in (("v.name", filters.investor), ("i.stage", filters.stage)):
        if clean(value):
            relationships.append(f"casefold({column})=?")
            relation_parameters.append(clean(value).casefold())
    if relationships:
        clauses.append("EXISTS (SELECT 1 FROM investments i JOIN investors v ON v.id=i.investor_id "
                       "WHERE i.company_id=c.id AND " + " AND ".join(relationships) + ")")
        parameters.extend(relation_parameters)
    if clean(filters.keyword):
        keyword = clean(filters.keyword).casefold()
        clauses.append("(instr(casefold(c.raw_json),?)>0 OR EXISTS (SELECT 1 FROM investments i "
                       "JOIN investors v ON v.id=i.investor_id WHERE i.company_id=c.id AND "
                       "(instr(casefold(i.raw_json),?)>0 OR instr(casefold(v.name),?)>0)))")
        parameters.extend([keyword] * 3)
    sql = "SELECT c.* FROM companies c" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    rows = connection.execute(sql + " ORDER BY casefold(c.name),c.id LIMIT ? OFFSET ?",
                              (*parameters, filters.limit, filters.offset)).fetchall()
    results = []
    for row in rows:
        relationships = tuple(dict(item) for item in connection.execute(
            "SELECT i.*,v.name AS investor,v.country AS investor_country FROM investments i "
            "JOIN investors v ON v.id=i.investor_id WHERE i.company_id=? ORDER BY v.name,i.id", (row["id"],)))
        results.append(CompanyResult(id=row["id"], name=row["name"], country=row["country"],
            clinical_category=row["clinical_category"], clinical_use_case=row["clinical_use_case"],
            total_funding_amount=row["total_funding_amount"], total_funding_currency=row["total_funding_currency"],
            revenue_amount=row["revenue_amount"], revenue_currency=row["revenue_currency"], investments=relationships))
    return results


def search_documents(connection: sqlite3.Connection, *, keyword: str | None = None,
                     fund_name: str | None = None, limit: int = 100, offset: int = 0) -> list[DocumentResult]:
    _paging(QueryFilters(limit=limit, offset=offset))
    clauses, parameters = [], []
    if clean(keyword):
        clauses.append("instr(casefold(raw_json),?)>0")
        parameters.append(clean(keyword).casefold())
    if clean(fund_name):
        clauses.append("casefold(fund_name)=?")
        parameters.append(clean(fund_name).casefold())
    sql = "SELECT * FROM source_documents" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    return [DocumentResult(**{field: row[field] for field in DocumentResult.__dataclass_fields__})
            for row in connection.execute(sql + " ORDER BY source_id LIMIT ? OFFSET ?", (*parameters, limit, offset))]


def provenance(connection: sqlite3.Connection, entity_table: str, entity_id: str) -> list[dict]:
    if entity_table not in {"companies", "investors", "investments", "source_documents"}:
        raise ValueError("Unknown entity table")
    return [dict(row) for row in connection.execute("""SELECT c.*,r.input_filename,r.input_path,
        r.file_sha256,r.row_number,r.end_line_number,r.dataset FROM source_claims c
        JOIN source_rows r ON r.id=c.source_row_id WHERE c.entity_table=? AND c.entity_id=?
        ORDER BY r.input_path,r.file_sha256,r.row_number,c.field_name""", (entity_table, entity_id))]
