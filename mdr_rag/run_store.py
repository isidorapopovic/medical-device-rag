"""Transactional run ledger only; canonical legacy assessment JSON is not mirrored."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import BudgetExceeded, StorageError


MIGRATIONS: tuple[tuple[str, ...], ...] = (
    ("""CREATE TABLE runs (
        id TEXT PRIMARY KEY, project_hash TEXT NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft','blocked','completed_with_gaps','reviewed')),
        max_calls INTEGER NOT NULL CHECK(max_calls > 0),
        max_input INTEGER NOT NULL CHECK(max_input > 0),
        max_output INTEGER NOT NULL CHECK(max_output > 0),
        max_usd REAL NOT NULL CHECK(max_usd >= 0),
        error_code TEXT, elapsed_ms INTEGER NOT NULL DEFAULT 0 CHECK(elapsed_ms >= 0))""",
     """CREATE TABLE reservations (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
        input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
        output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
        usd REAL NOT NULL CHECK(usd >= 0), estimated INTEGER NOT NULL CHECK(estimated IN (0,1)),
        outcome TEXT NOT NULL CHECK(outcome IN ('reserved','completed','failed')),
        UNIQUE(run_id,id))"""),
    ("CREATE INDEX reservations_run_id ON reservations(run_id)",),
)


class RunStore:
    def __init__(self, path: Path, timeout: float = 2):
        self.path, self.timeout = path, timeout
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, timeout=timeout, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.migrate()
        except (sqlite3.Error, OSError):
            if hasattr(self, "connection"):
                self.connection.close()
            raise StorageError() from None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except BaseException as exc:
            if self.connection.in_transaction:
                self.connection.rollback()
            if isinstance(exc, (sqlite3.Error, OSError)):
                raise StorageError() from None
            raise

    def migrate(self, migrations: tuple[tuple[str, ...], ...] = MIGRATIONS) -> None:
        """All pending DDL and version rows commit together, including a fresh schema."""
        with self.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
            versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            if versions != list(range(1, len(versions) + 1)) or len(versions) > len(migrations):
                raise StorageError()
            for index, statements in enumerate(migrations[len(versions):], start=len(versions) + 1):
                for statement in statements:
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations VALUES (?)", (index,))

    def create_run(self, run_id: str, project_hash: str, created_at: str, settings) -> None:
        with self.transaction() as conn:
            conn.execute("""INSERT INTO runs
                (id,project_hash,created_at,status,max_calls,max_input,max_output,max_usd)
                VALUES (?,?,?,'draft',?,?,?,?)""", (run_id, project_hash, created_at,
                    settings.max_llm_calls_per_run, settings.max_run_input_tokens,
                    settings.max_run_output_tokens, settings.max_cloud_spend_usd))

    def usage(self, run_id: str) -> dict:
        try:
            row = self.connection.execute("""SELECT COUNT(*) calls, COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens, COALESCE(SUM(usd),0) usd,
                COALESCE(MAX(estimated),0) estimated FROM reservations WHERE run_id=?""", (run_id,)).fetchone()
            return dict(row)
        except sqlite3.Error:
            raise StorageError() from None

    def reserve(self, run_id: str, reservation_id: str, input_tokens: int, output_tokens: int, usd: float) -> None:
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)) or not 0 <= usd < float("inf"):
            raise ValueError("Invalid reservation")
        with self.transaction() as conn:
            limits = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if limits is None or limits["status"] != "draft":
                raise BudgetExceeded()
            usage = self.usage(run_id)
            if (usage["calls"] + 1 > limits["max_calls"]
                    or usage["input_tokens"] + input_tokens > limits["max_input"]
                    or usage["output_tokens"] + output_tokens > limits["max_output"]
                    or usage["usd"] + usd > limits["max_usd"]):
                raise BudgetExceeded()
            conn.execute("INSERT INTO reservations VALUES (?,?,?,?,?,?,?)",
                         (reservation_id, run_id, input_tokens, output_tokens, usd, 1, "reserved"))

    def reconcile(self, reservation_id: str, input_tokens: int | None, output_tokens: int | None,
                  *, outcome: str = "completed") -> None:
        for count in (input_tokens, output_tokens):
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("Invalid measured usage")
        if outcome not in {"completed", "failed"}:
            raise ValueError("Invalid reservation outcome")
        with self.transaction() as conn:
            current = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if current is None or current["outcome"] != "reserved":
                raise StorageError()
            # Failed calls retain the full reserve; unknown counters never become zero.
            known = outcome == "completed" and input_tokens is not None and output_tokens is not None
            conn.execute("""UPDATE reservations SET input_tokens=?,output_tokens=?,estimated=?,outcome=? WHERE id=?""",
                         (input_tokens if known else current["input_tokens"],
                          output_tokens if known else current["output_tokens"], int(not known), outcome, reservation_id))
        usage = self.usage(current["run_id"])
        limits = self.connection.execute("SELECT * FROM runs WHERE id=?", (current["run_id"],)).fetchone()
        if usage["input_tokens"] > limits["max_input"] or usage["output_tokens"] > limits["max_output"]:
            self.finish(current["run_id"], "blocked", "budget_exceeded", 0)
            raise BudgetExceeded()

    def finish(self, run_id: str, status: str, error_code: str | None, elapsed_ms: int) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE runs SET status=?,error_code=?,elapsed_ms=? WHERE id=?",
                         (status, error_code, elapsed_ms, run_id))

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
