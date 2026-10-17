"""Explicit local registry administration. Imports never carry approval authority."""
import json
from datetime import date
from pathlib import Path

from .ingestion import IngestionStore
from .regulatory_registry import (Edition, RegistryBundle, RegistryExport, RegistryStore,
                                  ReviewAttestation, import_draft)


def add_commands(subs) -> None:
    for name in ("registry-import", "registry-export", "registry-review", "registry-coverage", "registry-check", "registry-schema"):
        parser = subs.add_parser(name, help="Offline legal registry " + name.split("-")[1])
        parser.add_argument("--project-id", default="local")
        parser.add_argument("--fixture-only", action="store_true", help="Isolated synthetic tests; never authoritative law")
        if name == "registry-schema":
            continue
        if name in {"registry-import", "registry-export"}:
            parser.add_argument("--file", required=True)
        if name == "registry-import":
            parser.add_argument("--draft", help="Explicit requirements_draft.json conversion; --file must contain Edition JSON")
        if name in {"registry-import", "registry-review"}:
            parser.add_argument("--reviewer", required=True)
            parser.add_argument("--reason", required=True)
            parser.add_argument("--expected-revision", required=True, type=int)
            parser.add_argument("--operation-id", required=True)
        if name == "registry-review":
            parser.add_argument("--table", choices=["editions", "requirements", "coverage"], required=True)
            parser.add_argument("--id", required=True)
            parser.add_argument("--target", choices=["source_verified", "specialist_reviewed", "active", "rejected", "retired"], required=True)
            parser.add_argument("--as-of", required=True)
            parser.add_argument("--review-until", required=True)
            parser.add_argument("--official-origin-checked", action="store_true")
            parser.add_argument("--rights-checked", action="store_true")
        if name in {"registry-coverage", "registry-check"}:
            parser.add_argument("--edition", required=True)
            parser.add_argument("--as-of", required=True)


def read_json(path: str):
    file = Path(path)
    with file.open("rb") as stream:
        payload = stream.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError("Registry import exceeds JSON resource limit")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Invalid registry JSON") from None


def validate(model, data):
    try:
        return model.model_validate(data)
    except ValueError:
        raise ValueError("Invalid registry schema") from None


def execute(args, state: Path) -> None:
    if args.command == "registry-schema":
        print(json.dumps({"bundle": RegistryBundle.model_json_schema(),
                          "export": RegistryExport.model_json_schema(),
                          "review": ReviewAttestation.model_json_schema()}, indent=2))
        return
    archive = IngestionStore(state / "ingestion", args.project_id)
    with RegistryStore(state / "regulatory_registry", archive, fixture_only=args.fixture_only) as registry:
        if args.command == "registry-import":
            data = read_json(args.file)
            if not isinstance(data, dict):
                raise ValueError("Invalid registry schema")
            if args.draft:
                bundle = import_draft(read_json(args.draft), validate(Edition, data), archive)
            else:
                bundle = validate(RegistryExport, data).bundle if "bundle" in data else validate(RegistryBundle, data)
            revision = registry.import_bundle(bundle, expected_revision=args.expected_revision,
                operation_id=args.operation_id, reviewer=args.reviewer, reason=args.reason)
            result = {"revision": revision, "imported_as": "proposed", "fixture_only": args.fixture_only}
        elif args.command == "registry-review":
            attestation = ReviewAttestation(reviewer=args.reviewer, reason=args.reason,
                as_of=args.as_of, review_until=args.review_until,
                official_origin_checked=args.official_origin_checked, rights_checked=args.rights_checked)
            revision = registry.transition(args.table, args.id, args.target, attestation,
                expected_revision=args.expected_revision, operation_id=args.operation_id)
            result = {"revision": revision, "status": args.target}
        elif args.command == "registry-export":
            result = registry.export().model_dump(mode="json")
            # No accidental overwrite of an existing legal export or source file.
            destination = Path(args.file)
            from .ingestion import atomic_bytes
            if destination.exists():
                raise FileExistsError("Registry export destination already exists")
            atomic_bytes(destination, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
            result = {"exported": True, "content_sha256": result["content_sha256"]}
        else:
            as_of = date.fromisoformat(args.as_of)
            if args.command == "registry-check":
                selected = registry.select(args.edition, as_of)
                result = {"ready_for_authoritative_applicability": True, "active_requirement_ids": [r.id for r in selected["requirements"]],
                          "coverage": selected["coverage"]}
            else:
                result = registry.coverage_report(args.edition, as_of)
        print(json.dumps(result, ensure_ascii=False, indent=2))
