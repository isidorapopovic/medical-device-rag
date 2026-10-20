"""Versioned SQLite storage; no MDR imports, Chroma collections or model clients."""
import json
import sqlite3
from pathlib import Path

from .models import DEFAULT_DB

SCHEMA = (
    """CREATE TABLE companies (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        country TEXT, clinical_category TEXT, clinical_use_case TEXT, founded_year INTEGER,
        total_funding_amount REAL, total_funding_currency TEXT,
        revenue_amount REAL, revenue_currency TEXT, revenue_year INTEGER,
        clinical_study_url TEXT, regulatory_status_as_reported TEXT,
        regulatory_independently_verified INTEGER NOT NULL DEFAULT 0 CHECK(regulatory_independently_verified=0),
        observed_date TEXT, raw_json TEXT NOT NULL,
        CHECK(total_funding_amount IS NULL OR total_funding_currency IS NOT NULL),
        CHECK(revenue_amount IS NULL OR revenue_currency IS NOT NULL))""",
    """CREATE TABLE investors (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        country TEXT, investor_type TEXT, raw_json TEXT NOT NULL)""",
    """CREATE TABLE investments (
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
        investor_id TEXT NOT NULL REFERENCES investors(id), relationship TEXT, stage TEXT, round_date TEXT,
        round_amount REAL, round_currency TEXT, amount_type TEXT,
        fund_check_amount REAL, fund_check_currency TEXT, verification_as_reported TEXT,
        independently_verified INTEGER NOT NULL DEFAULT 0 CHECK(independently_verified=0),
        observed_date TEXT, raw_json TEXT NOT NULL,
        CHECK(round_amount IS NULL OR round_currency IS NOT NULL),
        CHECK(fund_check_amount IS NULL OR fund_check_currency IS NOT NULL))""",
    """CREATE TABLE source_documents (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE, fund_name TEXT, title TEXT NOT NULL,
        document_type TEXT, year INTEGER, format TEXT, url TEXT, landing_page TEXT,
        verification_as_reported TEXT,
        independently_verified INTEGER NOT NULL DEFAULT 0 CHECK(independently_verified=0),
        observed_date TEXT, raw_json TEXT NOT NULL)""",
    """CREATE TABLE source_rows (
        id TEXT PRIMARY KEY, dataset TEXT NOT NULL, input_filename TEXT NOT NULL,
        input_path TEXT NOT NULL, file_sha256 TEXT NOT NULL,
        row_number INTEGER NOT NULL, end_line_number INTEGER NOT NULL, raw_json TEXT NOT NULL,
        UNIQUE(dataset,input_path,file_sha256,row_number))""",
    """CREATE TABLE source_claims (
        entity_table TEXT NOT NULL, entity_id TEXT NOT NULL,
        source_row_id TEXT NOT NULL REFERENCES source_rows(id), field_name TEXT NOT NULL,
        raw_value TEXT NOT NULL, normalized_value TEXT,
        independently_verified INTEGER NOT NULL DEFAULT 0 CHECK(independently_verified=0),
        PRIMARY KEY(entity_table,entity_id,source_row_id,field_name))""",
    "CREATE INDEX companies_country_category ON companies(country,clinical_category)",
    "CREATE INDEX investments_company ON investments(company_id)",
    "CREATE INDEX investments_investor_stage ON investments(investor_id,stage)",
    "CREATE INDEX investors_country ON investors(country)",
    "CREATE INDEX documents_fund ON source_documents(fund_name)",
    "CREATE INDEX claims_entity ON source_claims(entity_table,entity_id)",
)
TABLES = ("companies", "investors", "investments", "source_documents", "source_rows", "source_claims")


def connect(path: str | Path = DEFAULT_DB, *, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path).resolve()
    if readonly:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.create_function("casefold", 1, lambda value: (value or "").casefold(), deterministic=True)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        app_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables and not readonly and version == 0 and app_id == 0:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                for statement in SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA application_id=1447250225")
                connection.execute("PRAGMA user_version=1")
        elif version != 1 or app_id != 1447250225:
            raise ValueError("Not a supported VC database (schema 1 required); use a separate VC DB path")
        return connection
    except BaseException:
        connection.close()
        raise


def upsert(connection: sqlite3.Connection, table: str, values: dict) -> str:
    """Only internal table/column names enter SQL; source data are parameters."""
    if table not in TABLES:
        raise ValueError("Unknown VC table")
    current = connection.execute(f"SELECT * FROM {table} WHERE id=?", (values["id"],)).fetchone()
    if current and all(current[key] == value for key, value in values.items()):
        return "unchanged"
    columns = ",".join(values)
    updates = ",".join(f"{key}=excluded.{key}" for key in values if key != "id")
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in values)}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}", tuple(values.values()))
    return "updated" if current else "inserted"


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
