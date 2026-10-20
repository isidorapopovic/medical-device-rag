"""Separate FDA cache; never migrates or writes the Task 01 or MDR databases."""
import hashlib
import sqlite3
from pathlib import Path

from .database import json_text
from .regulatory_models import DEFAULT_FDA_DB, k_number

APPLICATION_ID = 1447249476


class FDAStore:
    def __init__(self, path: str | Path = DEFAULT_FDA_DB, *, readonly: bool = False):
        path = Path(path).resolve()
        if readonly:
            self.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path)
        conn = self.connection
        conn.row_factory = sqlite3.Row
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            if not tables and not readonly and version == 0 and app_id == 0:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("""CREATE TABLE fda_records (
                        k_number TEXT PRIMARY KEY, device_name TEXT, applicant TEXT,
                        decision_date TEXT, decision_code TEXT, decision_description TEXT,
                        product_code TEXT, medical_specialty TEXT, raw_json TEXT NOT NULL,
                        source_url TEXT NOT NULL, fetched_at TEXT NOT NULL, checked_at TEXT,
                        retrieval_status TEXT NOT NULL)""")
                    conn.execute("""CREATE TABLE fda_pages (
                        cache_key TEXT PRIMARY KEY, parameters_json TEXT NOT NULL,
                        raw_json TEXT NOT NULL, source_url TEXT NOT NULL, fetched_at TEXT NOT NULL,
                        retrieval_status TEXT NOT NULL)""")
                    conn.execute("CREATE INDEX fda_applicant_product ON fda_records(applicant,product_code)")
                    conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    conn.execute("PRAGMA user_version=1")
            elif app_id != APPLICATION_ID or version != 1:
                raise ValueError("Not a supported FDA cache; use a separate --fda-db path")
        except BaseException:
            conn.close()
            raise

    @staticmethod
    def cache_key(parameters: dict) -> str:
        return hashlib.sha256(json_text(parameters).encode()).hexdigest()

    def page(self, parameters: dict) -> dict | None:
        row = self.connection.execute("SELECT * FROM fda_pages WHERE cache_key=?", (self.cache_key(parameters),)).fetchone()
        return dict(row) if row else None

    def save(self, parameters: dict, payload: dict, source_url: str, fetched_at: str, records: list[dict]) -> None:
        with self.connection:
            self.connection.execute("""INSERT INTO fda_pages VALUES (?,?,?,?,?,?) ON CONFLICT(cache_key)
                DO UPDATE SET raw_json=excluded.raw_json,source_url=excluded.source_url,
                fetched_at=excluded.fetched_at,retrieval_status=excluded.retrieval_status""",
                (self.cache_key(parameters), json_text(parameters), json_text(payload), source_url, fetched_at, "fetched_official"))
            for record in records:
                columns = tuple(record)
                self.connection.execute(f"INSERT INTO fda_records ({','.join(columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(k_number) DO UPDATE SET "
                    + ",".join(f"{col}=excluded.{col}" for col in columns if col != "k_number"), tuple(record.values()))

    def records(self, *, identifier: str | None = None) -> list[dict]:
        if identifier:
            rows = self.connection.execute("SELECT * FROM fda_records WHERE k_number=?", (k_number(identifier),))
        else:
            rows = self.connection.execute("SELECT * FROM fda_records ORDER BY decision_date DESC,k_number")
        return [dict(row) for row in rows]

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
