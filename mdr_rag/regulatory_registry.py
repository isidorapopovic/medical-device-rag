"""Offline legal editions, exact provisions, human lifecycle and coverage gates.

Registry tables own new law metadata only; canonical assessments/source archives
and the invocation ledger keep their existing responsibilities. No legal fetch.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from functools import wraps
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .contracts import Contract, Id, Sha256
from .document_parsers import sha256
from .errors import FoundationError, StorageError
from .ingestion import IngestionStore, confined, records_from_manifest

Lifecycle = Literal["proposed", "source_verified", "specialist_reviewed", "active", "rejected", "retired"]
NEXT = {"proposed": "source_verified", "source_verified": "specialist_reviewed", "specialist_reviewed": "active"}


class RegistryNotReady(FoundationError):
    code = "legal_registry_not_ready"


def digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class Edition(Contract):
    id: Id
    regulation_id: Id
    jurisdiction: Id
    label: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    manifest_sha256: Sha256
    file_sha256: Sha256
    source_kind: Literal["binding_law", "nonbinding_guidance", "standard", "synthetic_fixture"]
    text_form: Literal["original", "consolidated", "amending", "guidance", "standard", "synthetic_fixture"]
    published: date | None = None
    amended: date | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    base_edition_id: Id | None = None
    supersedes: list[Id] = Field(default_factory=list, max_length=100)
    redistribution_rights_confirmed: bool = False

    @model_validator(mode="after")
    def metadata(self):
        if self.source_url is not None:
            url = urlsplit(self.source_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("Legal origin requires an HTTPS URL without credentials or fragments")
        if self.effective_until and (not self.effective_from or self.effective_until < self.effective_from):
            raise ValueError("Invalid legal effective interval")
        if self.published and self.amended and self.amended < self.published:
            raise ValueError("Amendment precedes publication")
        forms = {"binding_law": {"original", "consolidated", "amending"},
                 "nonbinding_guidance": {"guidance"}, "standard": {"standard"},
                 "synthetic_fixture": {"synthetic_fixture"}}
        if self.text_form not in forms[self.source_kind]:
            raise ValueError("Legal source kind and text form disagree")
        if self.source_kind == "synthetic_fixture" and not self.label.startswith("SYNTHETIC"):
            raise ValueError("Fixture editions must be explicitly synthetic")
        if self.id in self.supersedes or self.base_edition_id == self.id or len(set(self.supersedes)) != len(self.supersedes):
            raise ValueError("Invalid edition lineage")
        return self


class Provision(Contract):
    id: Id
    edition_id: Id
    section_path: list[str] = Field(min_length=1, max_length=12)
    obligation_key: Id = "main"
    source_span_id: Id
    physical_page_1based: int | None = Field(default=None, ge=1, strict=True)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    exact_quote: str = Field(min_length=1, max_length=10000)
    quote_sha256: Sha256
    effective_from: date | None = None
    effective_until: date | None = None
    dependencies: list[Id] = Field(default_factory=list, max_length=100)
    evidence_type_tags: list[Id] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def integrity(self):
        if not self.id.startswith(self.edition_id + "."):
            raise ValueError("Provision ID must be namespaced by its edition")
        if self.end - self.start != len(self.exact_quote) or sha256(self.exact_quote.encode("utf-8")) != self.quote_sha256:
            raise ValueError("Legal quote bounds/hash mismatch")
        if any(not p.strip() or "/" in p or len(p) > 200 for p in self.section_path):
            raise ValueError("Invalid legal hierarchy path")
        if self.effective_until and (not self.effective_from or self.effective_until < self.effective_from):
            raise ValueError("Invalid provision effective interval")
        if self.id in self.dependencies or len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("Invalid provision dependencies")
        return self


class CoverageManifest(Contract):
    id: Id
    edition_id: Id
    scope_label: str = Field(min_length=1, max_length=500)
    expected_paths: list[str] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def paths(self):
        if len(set(self.expected_paths)) != len(self.expected_paths) or any(not p.strip() or len(p) > 2000 for p in self.expected_paths):
            raise ValueError("Invalid expected coverage inventory")
        return self


class RegistryBundle(Contract):
    schema_version: Literal[1] = 1
    project_id: Id
    fixture_only: bool = False
    editions: list[Edition] = Field(default_factory=list, max_length=100)
    requirements: list[Provision] = Field(default_factory=list, max_length=10000)
    coverage: list[CoverageManifest] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        for values in (self.editions, self.requirements, self.coverage):
            if len({v.id for v in values}) != len(values):
                raise ValueError("Duplicate registry IDs")
        return self


class ReviewAttestation(Contract):
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    as_of: date
    review_until: date
    official_origin_checked: bool = False
    rights_checked: bool = False

    @model_validator(mode="after")
    def interval(self):
        if self.review_until < self.as_of or not self.reviewer.strip() or not self.reason.strip():
            raise ValueError("Invalid reviewer or verification interval")
        return self


class RegistryExport(Contract):
    schema_version: Literal[1] = 1
    bundle: RegistryBundle
    content_sha256: Sha256
    revision: int = Field(ge=0, strict=True)
    lifecycle: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def integrity(self):
        if digest(self.bundle.model_dump(mode="json")) != self.content_sha256:
            raise ValueError("Registry bundle hash mismatch")
        return self


MIGRATIONS = ((
    "CREATE TABLE registry_meta (id INTEGER PRIMARY KEY CHECK(id=1), project_id TEXT NOT NULL, fixture_only INTEGER NOT NULL, revision INTEGER NOT NULL)",
    "CREATE TABLE editions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, content_sha256 TEXT NOT NULL, status TEXT NOT NULL, attestation TEXT)",
    "CREATE TABLE requirements (id TEXT PRIMARY KEY, edition_id TEXT NOT NULL REFERENCES editions(id), clause_sha256 TEXT NOT NULL, payload TEXT NOT NULL, content_sha256 TEXT NOT NULL, status TEXT NOT NULL, attestation TEXT, UNIQUE(edition_id,clause_sha256))",
    "CREATE TABLE coverage (id TEXT PRIMARY KEY, edition_id TEXT NOT NULL REFERENCES editions(id), payload TEXT NOT NULL, content_sha256 TEXT NOT NULL, status TEXT NOT NULL, attestation TEXT)",
    "CREATE TABLE registry_events (operation_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, revision INTEGER UNIQUE NOT NULL, event_json TEXT NOT NULL)",
),)


def coherent_read(function):
    @wraps(function)
    def wrapper(self, *args, **kwargs):
        if self.connection.in_transaction:
            return function(self, *args, **kwargs)
        with self.transaction():
            return function(self, *args, **kwargs)
    return wrapper


class RegistryStore:
    def __init__(self, root: Path, archive: IngestionStore, *, fixture_only: bool = False):
        self.archive, self.fixture_only = archive, fixture_only
        self.path = confined(root, root / archive.project_key / "registry.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = sqlite3.connect(self.path, timeout=2, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            with self.transaction() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS registry_migrations (version INTEGER PRIMARY KEY)")
                versions = [r[0] for r in conn.execute("SELECT version FROM registry_migrations ORDER BY version")]
                if versions != list(range(1, len(versions) + 1)) or len(versions) > len(MIGRATIONS):
                    raise StorageError()
                for version, statements in enumerate(MIGRATIONS[len(versions):], len(versions) + 1):
                    for statement in statements:
                        conn.execute(statement)
                    conn.execute("INSERT INTO registry_migrations VALUES (?)", (version,))
                conn.execute("INSERT OR IGNORE INTO registry_meta VALUES (1,?,?,0)", (archive.project_id, int(fixture_only)))
                meta = conn.execute("SELECT * FROM registry_meta").fetchone()
                if meta["project_id"] != archive.project_id or bool(meta["fixture_only"]) != fixture_only:
                    raise ValueError("Registry project/fixture scope mismatch")
        except BaseException as exc:
            if hasattr(self, "connection"):
                self.connection.close()
            if isinstance(exc, (sqlite3.Error, OSError)):
                raise StorageError() from None
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
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

    @property
    def revision(self) -> int:
        return self.connection.execute("SELECT revision FROM registry_meta WHERE id=1").fetchone()[0]

    def _row(self, table: str, identifier: str):
        if table not in {"editions", "requirements", "coverage"}:
            raise ValueError("Invalid registry table")
        row = self.connection.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown registry entry")
        model = {"editions": Edition, "requirements": Provision, "coverage": CoverageManifest}[table]
        try:
            value = model.model_validate_json(row["payload"])
        except ValueError:
            raise ValueError("Invalid stored registry entry") from None
        if value.id != identifier or digest(value.model_dump(mode="json")) != row["content_sha256"]:
            raise ValueError("Registry entry hash/identity mismatch")
        return value, row

    def _check_edition(self, edition: Edition) -> None:
        if (edition.source_kind == "synthetic_fixture") != self.fixture_only:
            raise ValueError("Synthetic fixtures and real-source registries must remain separate")
        manifest = self.archive.load(edition.manifest_sha256)
        self.archive.original(manifest)
        if manifest.document.collection != "legal" or manifest.document.sha256 != edition.file_sha256:
            raise ValueError("Edition requires the exact archived legal original")
        if not manifest.spans:
            raise ValueError("Edition has no readable legal spans")

    def _check_provision(self, requirement: Provision, edition: Edition) -> None:
        self._check_edition(edition)
        view = self.archive.view(edition.manifest_sha256, requirement.source_span_id,
                                 start=requirement.start, end=requirement.end)
        if view["exact_quote"] != requirement.exact_quote or view["physical_page"] != requirement.physical_page_1based:
            raise ValueError("Forged legal quote/page binding")
        if view["extraction_method"] != "native" or {"ocr_unverified", "unreadable_text"} & set(view["quality_flags"]):
            raise ValueError("Unverified OCR cannot become trusted legal text")
        if requirement.effective_from and edition.effective_from and requirement.effective_from < edition.effective_from:
            raise ValueError("Provision predates its edition effective interval")
        if requirement.effective_until and edition.effective_until and requirement.effective_until > edition.effective_until:
            raise ValueError("Provision outlives its edition effective interval")

    def _operation(self, operation_id: str, expected_revision: int, request, work) -> int:
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 128:
            raise ValueError("Invalid registry operation ID")
        request_hash = digest([expected_revision, request])
        with self.transaction() as conn:
            old = conn.execute("SELECT * FROM registry_events WHERE operation_id=?", (operation_id,)).fetchone()
            if old:
                if old["request_sha256"] != request_hash:
                    raise ValueError("Registry operation ID reused with different input")
                return old["revision"]
            if type(expected_revision) is not int or expected_revision != self.revision:
                raise ValueError("Registry revision changed; reload before writing")
            before = self.revision
            details = work(conn)
            revision = before + 1
            event = {"created_at": datetime.now(timezone.utc).isoformat(), "request": request,
                     "before_revision": before, "details": details}
            conn.execute("INSERT INTO registry_events VALUES (?,?,?,?)", (operation_id, request_hash, revision, json.dumps(event)))
            conn.execute("UPDATE registry_meta SET revision=? WHERE id=1", (revision,))
            return revision

    def import_bundle(self, bundle: RegistryBundle, *, expected_revision: int, operation_id: str,
                      reviewer: str, reason: str) -> int:
        bundle = RegistryBundle.model_validate(bundle.model_dump())
        if bundle.project_id != self.archive.project_id or bundle.fixture_only != self.fixture_only:
            raise ValueError("Registry bundle project/fixture mismatch")
        if not reviewer.strip() or not reason.strip():
            raise ValueError("Registry import requires reviewer and reason")
        def work(conn):
            for edition in bundle.editions:
                self._check_edition(edition)
                self._insert(conn, "editions", edition)
            for requirement in bundle.requirements:
                edition, _ = self._row("editions", requirement.edition_id)
                self._check_provision(requirement, edition)
                self._insert(conn, "requirements", requirement)
            for coverage in bundle.coverage:
                self._row("editions", coverage.edition_id)
                self._insert(conn, "coverage", coverage)
            return {"imported_as": "proposed", "edition_ids": [v.id for v in bundle.editions],
                    "requirement_ids": [v.id for v in bundle.requirements],
                    "coverage_ids": [v.id for v in bundle.coverage]}
        return self._operation(operation_id, expected_revision,
            {"action": "import", "bundle_sha256": digest(bundle.model_dump(mode="json")), "reviewer": reviewer, "reason": reason}, work)

    def _insert(self, conn, table, item) -> None:
        payload = item.model_dump(mode="json")
        checksum = digest(payload)
        old = conn.execute(f"SELECT content_sha256 FROM {table} WHERE id=?", (item.id,)).fetchone()
        if old:
            if old[0] != checksum:
                raise ValueError("Immutable registry entry differs; create a new edition/entry ID")
            return
        if table == "editions":
            conn.execute("INSERT INTO editions VALUES (?,?,?,'proposed',NULL)", (item.id, json.dumps(payload), checksum))
        elif table == "requirements":
            if conn.execute("SELECT 1 FROM requirements WHERE edition_id=? AND clause_sha256=?", (item.edition_id, item.quote_sha256)).fetchone():
                raise ValueError("Duplicated legal clause in the same edition")
            conn.execute("INSERT INTO requirements VALUES (?,?,?,?,?,'proposed',NULL)",
                         (item.id, item.edition_id, item.quote_sha256, json.dumps(payload), checksum))
        else:
            conn.execute("INSERT INTO coverage VALUES (?,?,?,?,'proposed',NULL)", (item.id, item.edition_id, json.dumps(payload), checksum))

    def transition(self, table: str, identifier: str, target: Lifecycle, attestation: ReviewAttestation, *,
                   expected_revision: int, operation_id: str) -> int:
        attestation = ReviewAttestation.model_validate(attestation.model_dump())
        def work(conn):
            item, row = self._row(table, identifier)
            before = row["status"]
            allowed = (table == "coverage" and before == "proposed" and target == "active") or NEXT.get(before) == target
            allowed |= target == "rejected" and before in {"proposed", "source_verified", "specialist_reviewed"}
            allowed |= target == "retired" and before == "active"
            if not allowed:
                raise ValueError("Invalid registry lifecycle transition")
            if target not in {"rejected", "retired"}:
                edition = item if table == "editions" else self._row("editions", item.edition_id)[0]
                self._check_edition(edition)
                if not edition.source_url or not edition.effective_from:
                    raise ValueError("Legal approval requires official URL and effective date")
                if not attestation.official_origin_checked:
                    raise ValueError("Reviewer must attest official origin was checked")
                if edition.source_kind == "standard" and not (edition.redistribution_rights_confirmed and attestation.rights_checked):
                    raise ValueError("Standards require explicit rights attestation")
                if table != "editions":
                    _, parent = self._row("editions", item.edition_id)
                    if parent["status"] not in {"source_verified", "specialist_reviewed", "active"}:
                        raise ValueError("Edition must be source verified before reviewing its entries")
                    if target == "active" and parent["status"] != "active":
                        raise ValueError("Edition must be active before activating its entries")
                if table == "requirements":
                    self._check_provision(item, edition)
                    if target == "active":
                        self._live("editions", item.edition_id, attestation.as_of)
                        if ((item.effective_from and item.effective_from > attestation.as_of)
                                or (item.effective_until and item.effective_until < attestation.as_of)):
                            raise ValueError("Provision is not effective at review date")
                        self._dependency_check(item, attestation.as_of)
                        self._section_conflicts(item)
                if table == "editions" and target == "active":
                    self._lineage_check(edition)
                    if (edition.published and edition.published > attestation.as_of) or (edition.amended and edition.amended > attestation.as_of):
                        raise ValueError("Edition publication/amendment is after the review date")
                    if edition.effective_from > attestation.as_of or (edition.effective_until and edition.effective_until < attestation.as_of):
                        raise ValueError("Edition is not effective at review date")
                    for other_id, in conn.execute("SELECT id FROM editions WHERE status='active' AND id!=?", (identifier,)):
                        other, _ = self._row("editions", other_id)
                        if (other.regulation_id, other.jurisdiction) == (edition.regulation_id, edition.jurisdiction):
                            if self._overlap(edition.effective_from, edition.effective_until, other.effective_from, other.effective_until):
                                raise ValueError("Conflicting active amendments/editions; explicitly retire superseded edition")
            conn.execute(f"UPDATE {table} SET status=?,attestation=? WHERE id=?", (target, attestation.model_dump_json(), identifier))
            return {"table": table, "id": identifier, "before": before, "after": target}
        return self._operation(operation_id, expected_revision,
            {"action": "review", "table": table, "id": identifier, "target": target,
             "attestation": attestation.model_dump(mode="json")}, work)

    def _lineage_check(self, edition: Edition) -> None:
        complete = set()
        def walk(item, visiting, depth):
            if item.id in visiting or depth > 100 or len(complete) + len(visiting) > 1000:
                raise ValueError("Cyclic or overlarge amendment lineage")
            if item.id in complete:
                return
            visiting = visiting | {item.id}
            for identifier in [*item.supersedes, *([item.base_edition_id] if item.base_edition_id else [])]:
                parent, _ = self._row("editions", identifier)
                if (parent.regulation_id, parent.jurisdiction) != (edition.regulation_id, edition.jurisdiction):
                    raise ValueError("Amendment lineage regulation/jurisdiction mismatch")
                walk(parent, visiting, depth + 1)
            complete.add(item.id)
        walk(edition, set(), 0)

    @staticmethod
    def _overlap(start, end, other_start, other_end) -> bool:
        return max(start or date.min, other_start or date.min) <= min(end or date.max, other_end or date.max)

    def _live(self, table: str, identifier: str, as_of: date):
        item, row = self._row(table, identifier)
        if row["status"] != "active" or row["attestation"] is None:
            raise RegistryNotReady()
        review = ReviewAttestation.model_validate_json(row["attestation"])
        if not review.as_of <= as_of <= review.review_until:
            raise RegistryNotReady()
        if table in {"editions", "requirements"}:
            if (item.effective_from and item.effective_from > as_of) or (item.effective_until and item.effective_until < as_of):
                raise RegistryNotReady()
        return item

    def _dependency_check(self, requirement: Provision, as_of: date) -> None:
        for identifier in requirement.dependencies:
            dependency = self._live("requirements", identifier, as_of)
            if dependency.edition_id != requirement.edition_id:
                raise ValueError("Cross-edition dependencies require a separately reviewed combined scope")

    def _section_conflicts(self, requirement: Provision) -> None:
        for identifier, in self.connection.execute("SELECT id FROM requirements WHERE edition_id=? AND status='active' AND id!=?", (requirement.edition_id, requirement.id)):
            other, _ = self._row("requirements", identifier)
            if (other.section_path, other.obligation_key) == (requirement.section_path, requirement.obligation_key) and self._overlap(requirement.effective_from, requirement.effective_until, other.effective_from, other.effective_until):
                raise ValueError("Conflicting active text for the same section")

    @coherent_read
    def coverage_report(self, edition_id: str, as_of: date) -> dict:
        edition, edition_row = self._row("editions", edition_id)
        expected, scopes, active_paths, loaded = set(), [], set(), set()
        counts = {}
        warnings = ["uploaded_text_is_not_automatically_latest_law"]
        for identifier, in self.connection.execute("SELECT id FROM coverage WHERE edition_id=?", (edition_id,)):
            try:
                coverage = self._live("coverage", identifier, as_of)
            except RegistryNotReady:
                continue
            expected.update(coverage.expected_paths)
            scopes.append(coverage.scope_label)
        for identifier, in self.connection.execute("SELECT id FROM requirements WHERE edition_id=?", (edition_id,)):
            requirement, row = self._row("requirements", identifier)
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            path = "/".join(requirement.section_path)
            loaded.add(path)
            try:
                self._live("requirements", identifier, as_of)
                self._check_provision(requirement, edition)
                self._dependency_check(requirement, as_of)
                active_paths.add(path)
            except RegistryNotReady:
                warnings.append("inactive_or_stale_requirement")
        try:
            self._live("editions", edition_id, as_of)
        except RegistryNotReady:
            warnings.append("inactive_or_stale_edition")
        warnings.extend(self._amendment_warnings(edition, as_of))
        if not expected:
            warnings.append("manually_verified_coverage_manifest_missing")
        missing = sorted(expected - active_paths)
        complete = bool(expected) and not missing and not {"inactive_or_stale_edition", "unresolved_verified_amendment"} & set(warnings)
        return {"edition_id": edition_id, "as_of": as_of.isoformat(), "revision": self.revision,
                "coverage_status": "complete within manually selected scope" if complete else "partial registry coverage",
                "scope_labels": scopes, "expected_paths": sorted(expected), "loaded_paths": sorted(loaded),
                "active_paths": sorted(active_paths), "missing_paths": missing, "counts": counts,
                "validation_as_of": json.loads(edition_row["attestation"])["as_of"] if edition_row["attestation"] else None,
                "amendment_ids": edition.supersedes, "warnings": sorted(set(warnings)), "fixture_only": self.fixture_only}

    def _amendment_warnings(self, edition: Edition, as_of: date) -> list[str]:
        warnings = []
        for identifier, in self.connection.execute("SELECT id FROM editions WHERE id!=?", (edition.id,)):
            other, row = self._row("editions", identifier)
            if edition.id not in other.supersedes or not other.effective_from or other.effective_from > as_of:
                continue
            if row["status"] in {"source_verified", "specialist_reviewed", "active"}:
                warnings.append("unresolved_verified_amendment")
            elif row["status"] == "proposed":
                warnings.append("proposed_amendment_pending_review")
        return warnings

    @coherent_read
    def select(self, edition_id: str, as_of: date, *, allow_fixture: bool = False) -> dict:
        """The only gate supplying approved law to authoritative applicability callers."""
        if self.fixture_only and not allow_fixture:
            raise RegistryNotReady()
        if not self.connection.execute("SELECT 1 FROM editions WHERE id=?", (edition_id,)).fetchone():
            raise RegistryNotReady()
        edition = self._live("editions", edition_id, as_of)
        if edition.source_kind != "binding_law" and not (allow_fixture and edition.source_kind == "synthetic_fixture"):
            raise RegistryNotReady()
        self._check_edition(edition)
        if "unresolved_verified_amendment" in self._amendment_warnings(edition, as_of):
            raise RegistryNotReady()
        requirements = []
        for identifier, in self.connection.execute("SELECT id FROM requirements WHERE edition_id=? AND status='active' ORDER BY id", (edition_id,)):
            requirement = self._live("requirements", identifier, as_of)
            self._check_provision(requirement, edition)
            self._dependency_check(requirement, as_of)
            requirements.append(requirement)
        if not requirements:
            raise RegistryNotReady()
        return {"edition": edition, "requirements": requirements,
                "coverage": self.coverage_report(edition_id, as_of), "revision": self.revision}

    @coherent_read
    def export(self) -> RegistryExport:
        values, lifecycle = {}, {}
        for table in ("editions", "requirements", "coverage"):
            values[table] = []
            for identifier, in self.connection.execute(f"SELECT id FROM {table} ORDER BY id"):
                item, row = self._row(table, identifier)
                if table == "editions":
                    self._check_edition(item)
                    if item.source_kind == "standard":
                        rights = ReviewAttestation.model_validate_json(row["attestation"]) if row["attestation"] else None
                        if not item.redistribution_rights_confirmed or not rights or not rights.rights_checked:
                            raise ValueError("Standards export requires confirmed redistribution rights")
                values[table].append(item)
                lifecycle[table + ":" + identifier] = {"status": row["status"], "attestation": json.loads(row["attestation"]) if row["attestation"] else None}
        bundle = RegistryBundle(project_id=self.archive.project_id, fixture_only=self.fixture_only, **values)
        return RegistryExport(bundle=bundle, content_sha256=digest(bundle.model_dump(mode="json")), revision=self.revision, lifecycle=lifecycle)


def import_draft(draft: dict, edition: Edition, archive: IngestionStore) -> RegistryBundle:
    """Explicit legacy conversion; ignore human_validated and preserve draft status."""
    manifest = archive.load(edition.manifest_sha256)
    records = {record["id"]: record for record in records_from_manifest(manifest)}
    requirements = []
    for item in draft.get("requirements", []):
        record = records.get(item.get("legal_source_chunk_id"))
        quote = item.get("exact_quote", "")
        if (not record or not quote or record["meta"]["sha256"] != item.get("legal_sha256")
                or record["meta"]["page"] != item.get("legal_page") or record["meta"]["source"] != item.get("legal_source")):
            raise ValueError("Draft source does not match the archived legal revision")
        text = record["text"]
        start = item.get("legal_quote_start")
        if start is None:
            start = text.find(quote)
            if start < 0 or text.find(quote, start + 1) >= 0:
                raise ValueError("Draft quote must have unique exact offsets")
        requirements.append(Provision(id=edition.id + "." + item["id"], edition_id=edition.id,
            section_path=[item.get("provision", "unspecified")], source_span_id=record["meta"]["source_span_id"],
            physical_page_1based=record["meta"]["page"] or None, start=start, end=start + len(quote),
            exact_quote=quote, quote_sha256=sha256(quote.encode("utf-8"))))
    return RegistryBundle(project_id=archive.project_id, fixture_only=edition.source_kind == "synthetic_fixture",
                          editions=[edition], requirements=requirements)
