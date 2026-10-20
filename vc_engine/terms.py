"""Human-editable terminology with strict schema and non-executable formulas."""
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ROOT, clean, iso_date

DEFAULT_TERMS = ROOT / "data/vc/vc_terms.yaml"
DISCLAIMER = ("Educational research glossary, not legal/accounting/investment advice. "
              "Simplified formulas must not be applied to real deal documents without expert review. "
              "Formulas are documentation only; this registry never calculates metrics.")
CATEGORIES = {"valuation", "financing", "ownership", "operations", "market", "fund_performance",
              "deal_terms", "company_stage", "clinical", "regulatory"}
UNITS = {"currency": (1, 0, 0), "currency_per_month": (1, -1, 0), "currency_per_year": (1, -1, 0),
         "percentage": (0, 0, 0), "percentage_points": (0, 0, 0), "annualized_percentage": (0, 0, 0),
         "months": (0, 1, 0), "multiple": (0, 0, 0), "shares": (0, 0, 1), "not_applicable": None}


@dataclass(frozen=True)
class Term:
    id: str
    label: str
    aliases: tuple[str, ...]
    definition: str
    category: str
    formula: dict | None
    unit: str
    common_misinterpretations: tuple[str, ...]
    status: str
    references: tuple[str, ...] = ()
    reviewed_by: str | None = None
    review_note: str | None = None
    reviewed_on: str | None = None


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not clean(value):
        raise ValueError(f"{label} must be nonblank text")
    return clean(value)


def _strings(value, label: str, *, nonempty=False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} must be a {'nonempty ' if nonempty else ''}list of strings")
    return tuple(_text(item, label) for item in value)


def validate_formula(formula, output_unit: str) -> None:
    if formula is None:
        return
    if not isinstance(formula, dict) or set(formula) != {"expression", "variables", "caveats"}:
        raise ValueError("formula requires expression, variables and caveats")
    expression = _text(formula["expression"], "formula expression")
    variables = formula["variables"]
    _strings(formula["caveats"], "formula caveats", nonempty=True)
    if len(expression) > 500 or not isinstance(variables, dict) or not variables or len(variables) > 20:
        raise ValueError("Invalid formula expression/variables")
    if any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
           or not isinstance(unit, str) or unit not in UNITS or UNITS[unit] is None for key, unit in variables.items()):
        raise ValueError("Invalid formula variable name/unit")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError("Invalid formula syntax") from None
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("Formula is too complex")
    seen = set()

    def dimension(node):
        if isinstance(node, ast.Name) and node.id in variables:
            seen.add(node.id)
            return UNITS[variables[node.id]]
        if isinstance(node, ast.Constant) and type(node.value) in {int, float} and -1000000 <= node.value <= 1000000:
            return (0, 0, 0)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return dimension(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = dimension(node.left), dimension(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if left != right:
                    raise ValueError("Formula adds/subtracts incompatible units")
                return left
            if isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant) and node.right.value == 0:
                raise ValueError("Formula divides by literal zero")
            sign = -1 if isinstance(node.op, ast.Div) else 1
            return tuple(a + sign * b for a, b in zip(left, right))
        raise ValueError("Formula permits named variables, finite constants and + - * / only; no executable expressions")

    result = dimension(tree.body)
    if seen != set(variables) or UNITS[output_unit] is None or result != UNITS[output_unit]:
        raise ValueError("Formula variables/output unit do not agree")


def validate_registry(payload: dict) -> tuple[Term, ...]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "terms"} or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("Registry requires schema_version 1 and terms")
    if not isinstance(payload["terms"], list) or not 1 <= len(payload["terms"]) <= 500:
        raise ValueError("Registry needs 1–500 terms")
    required = {"id", "label", "aliases", "definition", "category", "formula", "unit", "common_misinterpretations", "status"}
    allowed = set(Term.__dataclass_fields__)
    result, identifiers, lookups = [], set(), {}
    for item in payload["terms"]:
        if not isinstance(item, dict) or set(item) - allowed or required - set(item):
            raise ValueError("Term has unknown or missing fields")
        scalar = {key: _text(item[key], key) for key in ("id", "label", "definition", "category", "unit", "status")}
        identifier = scalar["id"].casefold()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", scalar["id"]) or identifier in identifiers:
            raise ValueError("Invalid or duplicate term ID: " + scalar["id"])
        identifiers.add(identifier)
        if scalar["category"] not in CATEGORIES or scalar["unit"] not in UNITS or scalar["status"] not in {"draft", "reviewed"}:
            raise ValueError("Invalid term category, unit or status")
        aliases = _strings(item["aliases"], "aliases")
        if len({alias.casefold() for alias in aliases}) != len(aliases):
            raise ValueError("Duplicate aliases within term: " + scalar["id"])
        for lookup in (scalar["id"], scalar["label"], *aliases):
            normalized = lookup.casefold()
            if normalized in lookups and lookups[normalized] != identifier:
                raise ValueError("Duplicate/ambiguous term alias or label: " + lookup)
            lookups[normalized] = identifier
        validate_formula(item["formula"], scalar["unit"])
        review = {key: item.get(key) for key in ("reviewed_by", "review_note", "reviewed_on")}
        for key, value in review.items():
            if value is not None:
                review[key] = _text(value, key)
        if scalar["status"] == "reviewed" and (not all(review.values()) or iso_date(review["reviewed_on"]) is None):
            raise ValueError("Reviewed terms require reviewed_by, review_note and ISO reviewed_on")
        result.append(Term(**scalar, aliases=aliases, formula=item["formula"],
            common_misinterpretations=_strings(item["common_misinterpretations"], "common_misinterpretations", nonempty=True),
            references=_strings(item.get("references", []), "references"), **review))
    return tuple(result)


def load_terms(path: str | Path = DEFAULT_TERMS) -> tuple[Term, ...]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if len(text.encode()) > 1024 * 1024:
        raise ValueError("Term registry exceeds 1 MiB")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        try:
            import yaml
        except ImportError:
            raise RuntimeError("YAML registry requires PyYAML; install requirements.txt or pass a JSON registry") from None

        class UniqueLoader(yaml.SafeLoader):
            pass

        def mapping(loader, node):
            result = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=True)
                if not isinstance(key, str) or key in result:
                    raise ValueError("Duplicate or non-string YAML mapping key")
                result[key] = loader.construct_object(value_node, deep=True)
            return result

        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        UniqueLoader.add_constructor("tag:yaml.org,2002:timestamp", lambda loader, node: loader.construct_scalar(node))
        try:
            payload = yaml.load(text, Loader=UniqueLoader)
        except yaml.YAMLError as exc:
            raise ValueError("Invalid YAML registry") from exc
    return validate_registry(payload)


def lookup_term(query: str, *, path: str | Path = DEFAULT_TERMS) -> Term:
    query = _text(query, "Term query").casefold()
    for term in load_terms(path):
        if query in {text.casefold() for text in (term.id, term.label, *term.aliases)}:
            return term
    raise ValueError("Unknown VC term: " + query)


def search_terms(query: str | None = None, *, path: str | Path = DEFAULT_TERMS) -> list[Term]:
    terms = load_terms(path)
    query = clean(query).casefold() if clean(query) else None
    return [term for term in terms if query is None or query in " ".join((term.id, term.label, term.definition, *term.aliases)).casefold()]
