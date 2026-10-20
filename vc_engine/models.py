"""CSV contracts, conservative normalizers and typed query results."""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data/vc/medtech_vc.sqlite"
DEFAULT_REPORT = ROOT / "reports/vc_import_quality.json"
DEFAULT_FILES = {
    "companies": ROOT / "data/vc/raw/europe_ai_samd_50_companies.csv",
    "investments": ROOT / "data/vc/raw/europe_healthtech_vc_50_investments.csv",
    "source_documents": ROOT / "data/vc/raw/vc_public_real_documents.csv",
}
HEADERS = {
    "companies": tuple("company headquarters_country selected_device_or_software clinical_category clinical_use_case founded_year dealroom_reported_total_funding_usd_millions funding_source_url revenue_value revenue_year operating_profit_or_loss net_profit_or_loss profitability_status annual_financial_statement_url regulatory_status_as_reported regulatory_details device_or_regulatory_evidence_url ownership_as_of_2026_10_17 investment_diligence_priority business_model_to_verify clinical_evidence_study_url risk_flags research_date data_quality_note".split()),
    "investments": tuple("investor investor_type investor_country company product_or_platform product_category medical_device_or_samd_class investment_relationship reported_round_amount reported_round_currency amount_type round_stage round_date individual_fund_check_amount fund_check_disclosure fund_portfolio_source round_announcement_source classification_source fund_or_report_link verification_level diligence_notes additional_market_report as_of_date regulatory_note".split()),
    "source_documents": tuple("source_id fund_name document_title document_type year format direct_document_or_page_url official_landing_page relationship_to_listed_investor expected_extractable_fields verification_status research_priority important_notes observed_2026_10_16".split()),
}


def clean(value: str | None) -> str | None:
    value = unicodedata.normalize("NFC", " ".join((value or "").split()))
    return value or None


def stable_id(kind: str, *parts: str | None) -> str:
    payload = [clean(part).casefold() if clean(part) else "" for part in parts]
    return kind + "_" + hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def number(value: str | None) -> float | None:
    """Accept plain decimal or unambiguous thousands groups, never ranges/units."""
    value = clean(value)
    if not value or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?)", value):
        return None
    try:
        parsed = Decimal(value.replace(",", ""))
        result = float(parsed)
        return result if abs(result) < float("inf") else None
    except (InvalidOperation, OverflowError):
        return None


def year(value: str | None) -> int | None:
    value = clean(value)
    return int(value) if value and re.fullmatch(r"\d{4}", value) and 1 <= int(value) <= 9999 else None


def iso_date(value: str | None) -> str | None:
    value = clean(value)
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def currency(value: str | None) -> str | None:
    value = clean(value)
    return value.upper() if value and re.fullmatch(r"[A-Za-z]{3}", value) else None


@dataclass(frozen=True)
class QueryFilters:
    country: str | None = None
    clinical_category: str | None = None
    company: str | None = None
    investor: str | None = None
    stage: str | None = None
    keyword: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class CompanyResult:
    id: str
    name: str
    country: str | None
    clinical_category: str | None
    clinical_use_case: str | None
    total_funding_amount: float | None
    total_funding_currency: str | None
    revenue_amount: float | None
    revenue_currency: str | None
    investments: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DocumentResult:
    id: str
    source_id: str
    fund_name: str | None
    title: str
    url: str | None
    verification_as_reported: str | None
