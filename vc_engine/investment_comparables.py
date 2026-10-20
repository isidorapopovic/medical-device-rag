"""Read-only investment relationships with conservative company-name joins."""
import json
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .database import connect
from .models import DEFAULT_DB, clean
from .queries import provenance


@dataclass(frozen=True)
class InvestmentFilters:
    specialty: str | None = None
    indication: str | None = None
    country: str | None = None
    investor_country: str | None = None
    stage: str | None = None
    product_category: str | None = None
    company: str | None = None
    investor: str | None = None
    keyword: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class ReportedAmount:
    amount: float | None
    currency: str | None
    source_url: str | None
    as_of_date: str | None
    status: str = "claimed_only"


@dataclass(frozen=True)
class InvestmentComparable:
    investment_id: str
    investor_id: str
    investor: str
    investor_country: str | None
    company_id: str
    company: str
    company_country: str | None
    technology_or_product: str | None
    clinical_use_case: str | None
    specialty: str | None
    product_category: str | None
    stage: str | None
    round_date: str | None
    round_date_as_reported: str | None
    as_of_date: str | None
    relationship: str | None
    relationship_verification_note: str | None
    evidence_status: str
    reported_total_round_amount: ReportedAmount
    individual_fund_check: ReportedAmount
    company_cumulative_funding: ReportedAmount
    amount_type: str | None
    fund_check_disclosure: str | None
    join_status: str
    join_review: tuple[dict, ...]
    source_urls: tuple[str, ...]
    field_provenance: tuple[dict, ...]
    missing_data: tuple[str, ...]
    uncertainty_notes: tuple[str, ...]


@dataclass(frozen=True)
class InvestmentReport:
    results: tuple[InvestmentComparable, ...]
    filters: InvestmentFilters
    total_matching: int
    ambiguous_company_keys: tuple[dict, ...]
    limitations: tuple[str, ...]


def name_key(value: str | None) -> str:
    return (clean(value) or "").casefold()


def company_join_review(connection) -> dict[str, dict]:
    """Audit original catalog rows, because Task 01 normalized entity names alone.

    Material country/product conflicts require review; case/space variants alone
    are not collisions. History is retained and is not silently treated as resolved.
    """
    groups = {}
    for row in connection.execute("SELECT * FROM source_rows WHERE dataset='companies' ORDER BY id"):
        raw = json.loads(row["raw_json"])
        key = name_key(raw.get("company"))
        if not key:
            continue
        group = groups.setdefault(key, {"rows": [], "countries": set(), "products": set()})
        group["rows"].append(dict(source_id=row["id"], company=raw.get("company"),
            country=raw.get("headquarters_country"), product=raw.get("selected_device_or_software"),
            input_filename=row["input_filename"], row_number=row["row_number"], file_sha256=row["file_sha256"]))
        for bucket, field in (("countries", "headquarters_country"), ("products", "selected_device_or_software")):
            if name_key(raw.get(field)):
                group[bucket].add(name_key(raw[field]))
    return {key: dict(ambiguous=len(group["countries"]) > 1 or len(group["products"]) > 1,
                     rows=group["rows"], conflicting_fields=[field for field, bucket in (
                         ("headquarters_country", "countries"), ("selected_device_or_software", "products")) if len(group[bucket]) > 1])
            for key, group in groups.items()}


def investment_comparables(connection, filters: InvestmentFilters = InvestmentFilters(),
                           *, company_ids: set[str] | None = None) -> InvestmentReport:
    if type(filters.limit) is not int or not 1 <= filters.limit <= 1000 or type(filters.offset) is not int or filters.offset < 0:
        raise ValueError("Investment limit must be 1–1000 and offset nonnegative")
    reviews = company_join_review(connection)
    results = []
    for record in connection.execute("""SELECT i.*,v.name investor_name,v.country investor_country,
        c.name company_name,c.country company_country,c.clinical_category,c.clinical_use_case,
        c.total_funding_amount,c.total_funding_currency,c.observed_date company_observed_date,
        c.raw_json company_raw FROM investments i JOIN investors v ON v.id=i.investor_id
        JOIN companies c ON c.id=i.company_id ORDER BY i.id"""):
        row, raw, company_raw = dict(record), json.loads(record["raw_json"]), json.loads(record["company_raw"])
        if company_ids is not None and row["company_id"] not in company_ids:
            continue
        raw_company_key = name_key(raw.get("company"))
        review = reviews.get(raw_company_key)
        status = "ambiguous_name" if review and review["ambiguous"] else "exact_normalized_name" if review else "no_company_profile"
        if raw_company_key != name_key(row["company_name"]):
            status = "key_mismatch"
        joined = status == "exact_normalized_name"
        country = row["company_country"] if joined else None
        use_case = row["clinical_use_case"] if joined else None
        specialty = row["clinical_category"] if joined else None
        exact_fields = {"country": country, "investor_country": clean(raw.get("investor_country")),
                        "stage": row["stage"], "company": raw.get("company"), "investor": raw.get("investor")}
        if any(name_key(getattr(filters, key)) and name_key(value) != name_key(getattr(filters, key)) for key, value in exact_fields.items()):
            continue
        substring_fields = {"specialty": " ".join(filter(None, [specialty, raw.get("product_category")])),
                            "indication": use_case, "product_category": raw.get("product_category"),
                            "keyword": " ".join(str(value or "") for value in [*raw.values(), use_case, specialty])}
        if any(name_key(getattr(filters, key)) and name_key(getattr(filters, key)) not in name_key(value) for key, value in substring_fields.items()):
            continue
        as_of = row["observed_date"]
        round_source = clean(raw.get("round_announcement_source"))
        relationship_source = clean(raw.get("fund_portfolio_source"))
        funding_source = clean(company_raw.get("funding_source_url")) if joined else None
        cumulative = ReportedAmount(row["total_funding_amount"] if joined else None,
            row["total_funding_currency"] if joined else None, funding_source, row["company_observed_date"] if joined else None)
        missing = [key for key, value in {"company_country": country, "clinical_use_case": use_case,
            "round_stage": row["stage"], "round_date": row["round_date"], "reported_total_round_amount": row["round_amount"],
            "individual_fund_check": row["fund_check_amount"], "company_cumulative_funding": cumulative.amount}.items() if value is None]
        notes = ["CSV-reported relationship, not independently verified; reported verification text is retained literally.",
                 "Round total, separately disclosed individual check and cumulative funding are different measures; no check or ownership inferred.",
                 "Company cumulative funding is reported data (including the Dealroom column), not audited or independently checked."]
        if not joined:
            notes.append("Company-profile fields and cumulative funding withheld: " + status + "; inspect original source rows before relying on a join.")
        if raw.get("round_date") and not row["round_date"]:
            notes.append("Round date is partial/unparseable; original date text retained.")
        origins = tuple(dict(entity_table="investments", source_id=item["source_row_id"], field=item["field_name"], quote=item["raw_value"],
            input_filename=item["input_filename"], row_number=item["row_number"], file_sha256=item["file_sha256"], status="claimed_only")
            for item in provenance(connection, "investments", row["id"]))
        if joined:
            company_fields = {"company", "headquarters_country", "clinical_category", "clinical_use_case",
                              "dealroom_reported_total_funding_usd_millions", "funding_source_url", "research_date"}
            origins += tuple(dict(entity_table="companies", source_id=item["source_row_id"], field=item["field_name"], quote=item["raw_value"],
                input_filename=item["input_filename"], row_number=item["row_number"], file_sha256=item["file_sha256"], status="claimed_only")
                for item in provenance(connection, "companies", row["company_id"])
                if item["field_name"] in company_fields and item["raw_value"] == company_raw.get(item["field_name"]))
        results.append(InvestmentComparable(row["id"], row["investor_id"], raw.get("investor") or row["investor_name"],
            clean(raw.get("investor_country")), row["company_id"], clean(raw.get("company")) or row["company_name"], country,
            clean(raw.get("product_or_platform")), use_case, specialty, clean(raw.get("product_category")), row["stage"], row["round_date"],
            clean(raw.get("round_date")), as_of, row["relationship"], row["verification_as_reported"], "claimed_only",
            ReportedAmount(row["round_amount"], row["round_currency"], round_source, as_of),
            ReportedAmount(row["fund_check_amount"], row["fund_check_currency"], round_source or relationship_source, as_of),
            cumulative, row["amount_type"], clean(raw.get("fund_check_disclosure")), status,
            tuple(review["rows"]) if review and review["ambiguous"] else (),
            tuple(dict.fromkeys(url for url in (relationship_source, round_source, funding_source) if url)), origins,
            tuple(missing), tuple(notes)))
    ambiguous = tuple(dict(normalized_key=key, conflicting_fields=value["conflicting_fields"], sources=value["rows"])
                      for key, value in sorted(reviews.items()) if value["ambiguous"])
    return InvestmentReport(tuple(results[filters.offset:filters.offset + filters.limit]), filters, len(results), ambiguous,
        ("Explicit Unicode/whitespace/case-normalized name keys only; no fuzzy matching or automatic alias/subsidiary merging.",
         "Conflicting historical country/product records remain flagged for human review, not silently superseded.",
         "Country is company headquarters; investor_country is separately reported and never substituted.",
         "Specialty searches company clinical category and investment product category; indication uses the joined company clinical use case.",
         "Fund-document catalog entries do not create investment participation or financial facts."))


def query_investments(*, db: str | Path = DEFAULT_DB, filters: InvestmentFilters = InvestmentFilters(),
                      company_ids: set[str] | None = None) -> InvestmentReport:
    with closing(connect(db, readonly=True)) as connection:
        return investment_comparables(connection, filters, company_ids=company_ids)
