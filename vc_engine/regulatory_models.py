"""Research-only FDA 510(k) query contracts and evidence status."""
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import ROOT, clean

FDA_ENDPOINT = "https://api.fda.gov/device/510k.json"
DEFAULT_FDA_DB = ROOT / "data/vc/fda_510k.sqlite"
SCOPE = "FDA 510(k) research precedents only; excludes De Novo and PMA"
WARNINGS = (
    "510(k) clearance is not FDA approval.",
    "Similarity is not proof of substantial equivalence or a legally valid predicate.",
    "US clearance does not imply EU CE marking.",
    "Administrative record matches do not establish intended-use equivalence; intended use has not been compared.",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def k_number(value: str) -> str:
    value = (clean(value) or "").upper()
    if not re.fullmatch(r"K\d{6}", value):
        raise ValueError("k_number must be K followed by six digits")
    return value


def literal(value: str) -> str:
    """A literal phrase, not caller-supplied Lucene query syntax."""
    value = clean(value)
    if not value or len(value) > 300:
        raise ValueError("Search text must contain 1–300 characters")
    return '"' + re.sub(r'([+\-!(){}\[\]^"~*?:\\/&|])', r'\\\1', value) + '"'


@dataclass(frozen=True)
class FDAQuery:
    query: str | None = None
    device_name: str | None = None
    applicant: str | None = None
    product_code: str | None = None
    k_number: str | None = None

    def expression(self) -> str:
        parts = []
        if clean(self.query):
            parts.append("device_name:" + literal(self.query))
        for field in ("device_name", "applicant", "product_code", "k_number"):
            value = getattr(self, field)
            if not clean(value):
                continue
            if field == "k_number":
                value = k_number(value)
            if field == "product_code" and not re.fullmatch(r"[A-Za-z]{3}", value.strip()):
                raise ValueError("product_code must be three letters")
            # product_code has no .exact subfield on the live 510(k) endpoint.
            # Three-letter token search plus the local equality check is exact.
            if field == "product_code":
                parts.append(field + ":" + literal(value.strip().upper()))
            else:
                parts.append(field + ".exact:" + literal(value))
        if not parts:
            raise ValueError("Supply --query, --device-name, --applicant, --product-code or --k-number")
        return " AND ".join(parts)

    def matches(self, raw: dict) -> bool:
        """Check known exact fields locally as well; never trust a mismatched ID."""
        for field in ("device_name", "applicant", "product_code", "k_number"):
            expected = clean(getattr(self, field))
            actual = raw.get(field)
            if expected and (not isinstance(actual, str) or (clean(actual) or "").casefold() != expected.casefold()):
                return False
        return True


@dataclass(frozen=True)
class FetchLimits:
    page_size: int = 10
    max_pages: int = 5
    max_records: int = 100
    timeout: float = 15.0
    retries: int = 2
    backoff: float = 0.5
    min_interval: float = 0.3
    cache_hours: float = 24.0

    def validate(self) -> None:
        for field, maximum in (("page_size", 1000), ("max_pages", 25), ("max_records", 1000)):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{field} must be an integer from 1 to {maximum}")
        if type(self.retries) is not int or not 0 <= self.retries <= 3:
            raise ValueError("retries must be an integer from 0 to 3")
        for field, lower, upper in (("timeout", 0.1, 60), ("backoff", 0, 5),
                                    ("min_interval", 0.26, 10), ("cache_hours", 0, 8760)):
            if not lower <= getattr(self, field) <= upper:
                raise ValueError(f"{field} must be between {lower} and {upper}")


@dataclass(frozen=True)
class RegulatoryPrecedent:
    k_number: str
    device_name: str | None
    applicant: str | None
    decision_date: str | None
    decision_code: str | None
    decision_description: str | None
    product_code: str | None
    medical_specialty: str | None
    source_url: str
    source_checked_at: str | None
    fetched_at: str
    retrieval_status: str
    evidence_status: str
    verified_by_official_record: bool
    relevance_reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_urls: tuple[str, ...]
    raw_fda_response: dict


@dataclass(frozen=True)
class RegulatorySearchResult:
    query: FDAQuery
    results: tuple[RegulatoryPrecedent, ...]
    evidence_status: str
    scope: str = SCOPE
    warnings: tuple[str, ...] = WARNINGS
    limitations: tuple[str, ...] = ()
    checked_official_urls: tuple[str, ...] = ()
    pages_read: int = 0
    requests_made: int = 0
    records_seen: int = 0
    total_reported: int | None = None
    truncated: bool = False
