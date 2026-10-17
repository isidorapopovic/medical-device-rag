"""Explicit opt-in structural retrieval commands; defaults are unchanged."""
import json
from pathlib import Path

from .core import STATE, DOCS
from .ingestion import IngestionStore
from .structural_retrieval import StructuralIndex


def add_commands(subs):
    index = subs.add_parser("retrieval-index", help="Build an immutable structural index from archived source manifests")
    index.add_argument("--manifest", action="append", required=True)
    index.add_argument("--kind", choices=["legal", "device"], required=True)
    index.add_argument("--project-id", default="local")
    index.add_argument("--target", type=int, default=800)
    index.add_argument("--dense", action="store_true", help="Explicitly embed children with installed local Ollama model")
    retrieve = subs.add_parser("retrieve", help="Retrieve canonical parents from a structural snapshot; no answer generation")
    retrieve.add_argument("query")
    retrieve.add_argument("--snapshot", required=True)
    retrieve.add_argument("--project-id", default="local")
    retrieve.add_argument("--mode", choices=["bm25", "dense", "hybrid"], default="bm25")
    retrieve.add_argument("--backend", choices=["none", "llm", "cross_encoder"], default="none")
    retrieve.add_argument("--k", type=int, default=7)
    retrieve.add_argument("--expand", action="store_true")
    retrieve.add_argument("--assist", action="store_true", help="One optional bounded local selection of lexical intents")
    retrieve.add_argument("--documents-root", type=Path, default=DOCS,
                          help="Current working documents root; changed/deleted sources fail closed")


def run(args):
    store = IngestionStore(STATE / "ingestion", args.project_id)
    index = StructuralIndex(STATE / "retrieval", store)
    if args.command == "retrieval-index":
        key = index.build(args.manifest, args.kind, target=args.target, dense=args.dense)
        print(json.dumps({"snapshot": key, "structural": True, "dense_requested": args.dense,
                          "authoritative_legal_status": "not_assessed"}))
    else:
        if args.assist and not args.expand:
            raise ValueError("--assist requires --expand")
        from .query_expansion import expand_query
        plan = expand_query(args.query, scope=args.snapshot, assist=args.assist) if args.expand else None
        queries = [q.text for q in plan.queries] if plan else [args.query]
        result = index.retrieve(args.snapshot, queries, mode=args.mode, k=args.k,
                                backend=args.backend, documents_root=args.documents_root)
        result["query_plan"] = plan.model_dump() if plan else None
        print(json.dumps(result, ensure_ascii=False, indent=2))
