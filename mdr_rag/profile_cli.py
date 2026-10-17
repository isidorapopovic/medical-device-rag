"""Additive profile CLI; all output is explicit local preview/review data."""
import json
from pathlib import Path

from .device_profile import ProfileStore, extract_profile, import_legacy_profile
from .ingestion import IngestionStore


def add_commands(subs):
    for name in ("profile-extract", "profile-show", "profile-edit", "profile-import"):
        command = subs.add_parser(name, help="Evidence-linked device profile " + name.split("-")[1])
        command.add_argument("--project-id", default="local")
        if name in {"profile-extract", "profile-import"}:
            command.add_argument("--product", required=True)
        if name == "profile-extract":
            command.add_argument("--manifest", action="append", default=[])
            command.add_argument("--llm", action="store_true", help="Opt into bounded local Ollama extraction")
            command.add_argument("--save", action="store_true", help="Publish preview as an immutable review revision")
        if name == "profile-import":
            command.add_argument("--file", required=True)
        if name == "profile-show":
            command.add_argument("--revision", help="Historical revision SHA256; default is current")
        else:
            command.add_argument("--editor")
            command.add_argument("--reason")
            command.add_argument("--operation-id")
            command.add_argument("--expected-revision", help="Current SHA256 required when replacing/editing a profile")
        if name == "profile-edit":
            from .device_profile import FIELDS
            command.add_argument("--field", choices=FIELDS, required=True)
            command.add_argument("--action", choices=["confirm", "override", "reject"], required=True)
            values = command.add_mutually_exclusive_group()
            values.add_argument("--value")
            values.add_argument("--clear", action="store_true")


def execute(args, state: Path):
    archive = IngestionStore(state / "ingestion", args.project_id)
    profiles = ProfileStore(state / "profiles", archive)
    if args.command == "profile-show":
        revision, key = profiles.load(args.revision)
    else:
        saving = args.command != "profile-extract" or args.save
        if saving and not all((args.editor, args.reason, args.operation_id)):
            raise ValueError("Saving/review requires --editor, --reason and --operation-id")
        if args.command == "profile-edit":
            if not args.expected_revision:
                raise ValueError("Review requires --expected-revision")
            if args.action == "override" and args.value is None and not args.clear:
                raise ValueError("Override requires --value or --clear")
            revision, key = profiles.edit(args.field, action=args.action, value=args.value,
                editor=args.editor, reason=args.reason, expected_revision=args.expected_revision,
                operation_id=args.operation_id)
        else:
            if args.command == "profile-import":
                path = Path(args.file)
                if path.stat().st_size > 100000:
                    raise ValueError("Legacy profile size limit")
                preview = import_legacy_profile(json.loads(path.read_text(encoding="utf-8")),
                                                args.project_id, args.product)
            else:
                preview = extract_profile(archive, args.manifest, args.product, use_llm=args.llm)
            if not saving:
                print(preview.model_dump_json(indent=2))
                return
            revision, key = profiles.publish(preview, editor=args.editor, reason=args.reason,
                expected_revision=args.expected_revision, operation_id=args.operation_id,
                action="import" if args.command == "profile-import" else "extract")
    print(json.dumps({"revision_sha256": key, **revision.model_dump(mode="json")}, ensure_ascii=False, indent=2))
