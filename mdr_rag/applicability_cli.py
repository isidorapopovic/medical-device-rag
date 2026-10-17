"""Local rule administration and candidate applicability preview."""
import json
from datetime import date
from pathlib import Path

from .applicability_rules import ApplicabilityRule
from .applicability_service import ApplicabilityStore, ApplicabilityService, SpecialistApproval
from .ingestion import IngestionStore
from .registry_cli import read_json, validate
from .regulatory_registry import RegistryStore


def add_commands(subs) -> None:
    for name in ("applicability-schema", "applicability-show", "applicability-import",
                 "applicability-approve", "applicability-retire", "applicability-evaluate", "applicability-override"):
        parser = subs.add_parser(name, help="Candidate applicability " + name.split("-")[1])
        parser.add_argument("--project-id", default="local")
        if name == "applicability-schema":
            continue
        if name == "applicability-show":
            parser.add_argument("--revision", help="Historical rulebook SHA256")
            continue
        if name == "applicability-import":
            parser.add_argument("--file", required=True)
        if name in {"applicability-approve", "applicability-retire"}:
            parser.add_argument("--rule", required=True)
        if name not in {"applicability-retire"}:
            parser.add_argument("--as-of", required=True)
        if name in {"applicability-approve", "applicability-override"}:
            parser.add_argument("--specialist-reviewed", action="store_true")
        if name == "applicability-approve":
            parser.add_argument("--review-until", required=True)
        if name in {"applicability-evaluate", "applicability-override"}:
            parser.add_argument("--edition", required=True)
            parser.add_argument("--requirement", required=True)
        if name == "applicability-evaluate":
            parser.add_argument("--assist", action="store_true", help="Optional local clarification advice; never changes predicates")
        else:
            parser.add_argument("--reviewer", required=True)
            parser.add_argument("--reason", required=True)
            parser.add_argument("--operation-id", required=True)
            parser.add_argument("--expected-revision", type=int, required=True)
        if name == "applicability-override":
            parser.add_argument("--decision-key", required=True)
            parser.add_argument("--status", choices=["applicable", "not_applicable", "conditional", "unknown", "requires_human_review"], required=True)


def execute(args, state: Path) -> None:
    if args.command == "applicability-schema":
        print(json.dumps({"rule": ApplicabilityRule.model_json_schema(),
                          "approval": SpecialistApproval.model_json_schema()}, indent=2))
        return
    archive = IngestionStore(state / "ingestion", args.project_id)
    store = ApplicabilityStore(state / "applicability", archive)
    if args.command == "applicability-show":
        book, key = store.load(args.revision)
        print(json.dumps({"revision_sha256": key, **book.model_dump(mode="json")}, ensure_ascii=False, indent=2))
        return
    with RegistryStore(state / "regulatory_registry", archive) as registry:
        service = ApplicabilityService(store, registry)
        if args.command == "applicability-evaluate":
            result = service.evaluate(args.edition, args.requirement, date.fromisoformat(args.as_of), assist=args.assist)
        else:
            audit = dict(reviewer=args.reviewer, reason=args.reason,
                         expected_revision=args.expected_revision, operation_id=args.operation_id)
            if args.command == "applicability-import":
                rule = validate(ApplicabilityRule, read_json(args.file))
                book, key = service.import_rule(rule, as_of=date.fromisoformat(args.as_of), **audit)
            elif args.command == "applicability-approve":
                approval = validate(SpecialistApproval, dict(reviewer=args.reviewer, reason=args.reason,
                    as_of=args.as_of, review_until=args.review_until, specialist_reviewed=args.specialist_reviewed))
                book, key = service.approve_rule(args.rule, approval, **audit)
            elif args.command == "applicability-retire":
                book, key = service.retire_rule(args.rule, **audit)
            else:
                book, key = service.override(args.edition, args.requirement, date.fromisoformat(args.as_of),
                    args.status, decision_key=args.decision_key, specialist_reviewed=args.specialist_reviewed, **audit)
            result = {"revision": book.revision, "revision_sha256": key}
        print(json.dumps(result, ensure_ascii=False, indent=2))
