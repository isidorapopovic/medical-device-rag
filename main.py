"""Usage: python main.py --help"""
import argparse
import os
import sys

from dotenv import load_dotenv
from mdr_rag.core import ROOT
from mdr_rag.runtime import managed_run

load_dotenv(ROOT / ".env")
from mdr_rag.pipeline import (  # noqa: E402
    extract_requirements, inspect_files, run_ask, run_index, run_review
)


@managed_run
def main():
    parser = argparse.ArgumentParser(description="EU MDR source-grounded regulatory research")
    parser.add_argument(
        "--retrieval", choices=["dense", "bm25", "hybrid"], default=None,
        help="Override RETRIEVAL_MODE for this command (place before the command)",
    )
    rerank_options = parser.add_mutually_exclusive_group()
    rerank_options.add_argument(
        "--rerank", action="store_true",
        help="Use the local Ollama LLM to rerank retrieved candidates (slower)",
    )
    rerank_options.add_argument("--rerank-backend", "--reranker", choices=["none", "llm", "cross_encoder"],
                                help="Select a local reranker backend (before the command)")
    subs = parser.add_subparsers(dest="command", required=True)
    from mdr_rag.retrieval_cli import add_commands as add_retrieval_commands
    add_retrieval_commands(subs)
    subs.add_parser("inspect", help="List files and readable PDF pages")
    locate = subs.add_parser("locate", help="Find text to identify PDF page ranges")
    locate.add_argument("phrase", help='For example: "ANNEX I"')
    index = subs.add_parser("index", help="Rebuild the document vector index")
    index.add_argument("--force-reembed", action="store_true", help="Recompute every vector instead of reusing matching local vectors")
    ingest = subs.add_parser("ingest", help="Archive and parse one source revision without inference")
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--kind", required=True, choices=["legal", "device"])
    ingest.add_argument("--project-id", default="local")
    ingest.add_argument("--ocr", action="store_true", help="Explicit local OCR opt-in; also requires OCR_ENABLED=true")
    source_view = subs.add_parser("source-view", help="Open archived citation text and original revision metadata")
    source_view.add_argument("--manifest", required=True)
    source_view.add_argument("--span", required=True)
    source_view.add_argument("--project-id", default="local")
    source_view.add_argument("--start", type=int, default=0)
    source_view.add_argument("--end", type=int)
    source_view.add_argument("--context", type=int, default=160)
    ask = subs.add_parser("ask", help="Question-answering with verified source IDs")
    ask.add_argument("question")
    extract = subs.add_parser("extract", help="Draft requirements from ALL chunks on selected PDF pages")
    extract.add_argument("--pages", required=True, help='PDF page numbers, e.g. "89-92,94"')
    extract.add_argument("--legal-file", help="Filename in documents/legal")
    review = subs.add_parser("review", help="Map requirements to device evidence")
    review.add_argument("--registry-edition", help="Use only approved active legal registry provisions")
    review.add_argument("--registry-as-of", help="Explicit YYYY-MM-DD legal assessment date")
    review.add_argument("--limit", type=int, default=None, help="Only first N requirements (marks output partial)")
    review.add_argument("--k", type=int, default=None, help="Device chunks per requirement (new: 7; resume: saved value)")
    review.add_argument("--assessment-id", help="Persistent assessment ID (generated for a new run if omitted)")
    review.add_argument("--use-env-config", action="store_true", help="Explicitly adopt current environment settings and invalidate affected stages")
    review.add_argument("--resume", action="store_true", help="Continue pending, failed or stale checkpoints")
    review.add_argument("--requirement-id", help="Update only this existing requirement")
    review.add_argument("--refresh", action="store_true", help="Create a new finding revision for --requirement-id")
    report = subs.add_parser("report", help="Render saved assessment without inference")
    report.add_argument("--assessment-id", required=True)
    report.add_argument("--use-env-config", action="store_true", help="Check current environment configuration instead of saved settings")
    report.add_argument("--historical", action="store_true", help="Explicitly render a historical snapshot without current dependencies")
    report.add_argument("--revision", type=int, help="Saved state revision (requires --historical)")
    migrate = subs.add_parser("import-legacy", help="Non-destructively import a legacy assessment into a new ID")
    migrate.add_argument("--assessment", required=True)
    migrate.add_argument("--assessment-id", required=True)
    explorer = subs.add_parser("explore", help="Show candidate passages to label manually")
    explorer.add_argument("question")
    explorer.add_argument("--kind", choices=["legal", "device"], default="legal")
    explorer.add_argument("--k", type=int, default=8)
    embedmap = subs.add_parser("visualize-embeddings", help="PCA scatter of stored vectors")
    embedmap.add_argument("--sample", type=int, default=600)
    embedmap.add_argument("--query", default=None)
    embedmap.add_argument("--out", default=None)
    evaluate = subs.add_parser("evaluate", help="Retrieval metrics against human-labeled gold")
    evaluate.add_argument("--gold", default=None)
    evaluate.add_argument("--ks", type=int, nargs="+", default=[3, 5, 10])
    evaluate.add_argument("--out", default=None)
    evaluate.add_argument("--compare-all", action="store_true", help="Compare production single/multi-query, cross-encoder and complete review paths")
    evaluate.add_argument("--methods", nargs="+", help="Explicit production method names; complete review methods require held-out register IDs")
    evaluate.add_argument("--run-id", help="Distinct evaluation run ID")
    evaluate.add_argument("--saved-evaluation", help="Frozen evaluation JSON for offline human grounding adjudication")
    evaluate.add_argument("--grounding-labels", help="Human claim adjudications bound to frozen assessment revisions")
    evaluate.add_argument("--gate-labels", help="Evaluate reviewed scored runs on held-out answerable/unanswerable cases")
    evaluate.add_argument("--gate-calibration", help="Frozen calibration artifact for --gate-labels")
    calibrate = subs.add_parser("calibrate-gate", help="Tune a passage relevance threshold from reviewed saved runs")
    calibrate.add_argument("--labels", required=True)
    calibrate.add_argument("--out", required=True)
    graph = subs.add_parser("graph", help="HTML citation provenance graph from assessment")
    graph.add_argument("--assessment", default=None)
    graph.add_argument("--out", default=None)
    graph.add_argument("--max-requirements", type=int, default=140)
    from mdr_rag.profile_cli import add_commands
    add_commands(subs)
    from mdr_rag.registry_cli import add_commands as add_registry_commands
    add_registry_commands(subs)
    from mdr_rag.applicability_cli import add_commands as add_applicability_commands
    add_applicability_commands(subs)
    args = parser.parse_args()
    if args.retrieval is not None:
        os.environ["RETRIEVAL_MODE"] = args.retrieval
    if args.rerank:
        os.environ["RERANK_ENABLED"] = "true"
        os.environ["RERANK_BACKEND"] = "llm"
    if args.rerank_backend is not None:
        os.environ["RERANK_BACKEND"] = args.rerank_backend
        os.environ["RERANK_ENABLED"] = "false" if args.rerank_backend == "none" else "true"
    config_overrides = {}
    if args.retrieval is not None:
        config_overrides["retrieval_mode"] = args.retrieval
    if args.rerank or args.rerank_backend is not None:
        config_overrides["reranker_backend"] = "llm" if args.rerank else args.rerank_backend
    try:
        if args.command.startswith("applicability-"):
            from mdr_rag.applicability_cli import execute as execute_applicability
            from mdr_rag.core import STATE
            execute_applicability(args, STATE)
        elif args.command.startswith("registry-"):
            from mdr_rag.registry_cli import execute as execute_registry
            from mdr_rag.core import STATE
            execute_registry(args, STATE)
        elif args.command.startswith("profile-"):
            from mdr_rag.profile_cli import execute
            from mdr_rag.core import STATE
            execute(args, STATE)
        elif args.command == "inspect":
            inspect_files()
        elif args.command == "locate":
            inspect_files(args.phrase)
        elif args.command == "index":
            run_index(force_reembed=True) if args.force_reembed else run_index()
        elif args.command in {"ingest", "source-view"}:
            import json
            from pathlib import Path
            from mdr_rag.core import STATE
            from mdr_rag.ingestion import IngestionStore
            store = IngestionStore(STATE / "ingestion", args.project_id)
            if args.command == "source-view":
                print(json.dumps(store.view(args.manifest, args.span, start=args.start, end=args.end,
                                            context=args.context), ensure_ascii=False, indent=2))
            else:
                from mdr_rag.document_parsers import TesseractOCR
                from mdr_rag.settings import load_settings
                path = Path(args.file).resolve()
                if args.ocr and not load_settings().ocr_enabled:
                    raise ValueError("Local OCR requires OCR_ENABLED=true and --ocr")
                from mdr_rag.document_parsers import MAX_BYTES
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError("upload_exceeds_50_mib")
                document, manifest_hash = store.ingest(args.kind, path.name, path.read_bytes(),
                    ocr_enabled=args.ocr, ocr=TesseractOCR() if args.ocr else None)
                print(json.dumps(dict(document=document.document.model_dump(mode="json"),
                    status=document.extraction.status, manifest_sha256=manifest_hash,
                    source_span_ids=[span.id for span in document.spans],
                    diagnostics=document.extraction.diagnostics), ensure_ascii=False, indent=2))
        elif args.command in {"retrieval-index", "retrieve"}:
            from mdr_rag.retrieval_cli import run as run_retrieval
            run_retrieval(args)
        elif args.command == "ask":
            run_ask(args.question)
        elif args.command == "extract":
            extract_requirements(args.pages, args.legal_file)
        elif args.command == "review":
            run_review(args.limit, args.k, assessment_id=args.assessment_id, resume=args.resume,
                       requirement_id=args.requirement_id, refresh=args.refresh, config_overrides=config_overrides, use_env_config=args.use_env_config, **({"registry_edition": args.registry_edition, "registry_as_of": args.registry_as_of} if args.registry_edition or args.registry_as_of else {}))
        elif args.command == "report":
            from mdr_rag.review_state import render_report
            render_report(args.assessment_id, historical=args.historical, revision=args.revision, config_overrides=config_overrides, use_env_config=args.use_env_config)
        elif args.command == "import-legacy":
            from pathlib import Path
            from mdr_rag.core import STATE
            from mdr_rag.report_state import import_legacy, export_report, StateStore
            state = import_legacy(Path(args.assessment), STATE, args.assessment_id)
            destination = StateStore(STATE, args.assessment_id).directory / "legacy-import"
            export_report(state, destination, historical=True)
            print(f"Imported unverified legacy snapshot; exports: {destination}")
        elif args.command == "explore":
            from mdr_rag.evaluation import inspect_candidates
            inspect_candidates(args.question, args.kind, args.k)
        elif args.command == "visualize-embeddings":
            from mdr_rag.embedding_viz import visualize_embeddings
            visualize_embeddings(args.sample, args.query, args.out)
        elif args.command == "calibrate-gate":
            from mdr_rag.gate_evaluation import calibrate_labels
            calibrate_labels(args.labels, args.out)
        elif args.command == "evaluate":
            if args.saved_evaluation or args.grounding_labels:
                if not (args.saved_evaluation and args.grounding_labels and args.out):
                    raise ValueError("Offline grounding requires --saved-evaluation, --grounding-labels and --out")
                from mdr_rag.grounding_evaluation import adjudicate
                adjudicate(args.saved_evaluation, args.grounding_labels, args.out)
                return 0
            if args.gate_labels:
                if not args.gate_calibration or not args.out:
                    raise ValueError("--gate-labels requires --gate-calibration and --out")
                from mdr_rag.gate_evaluation import evaluate_labels
                evaluate_labels(args.gate_labels, args.gate_calibration, args.out)
                return 0
            if args.gate_calibration:
                raise ValueError("--gate-calibration requires --gate-labels")
            from mdr_rag.evaluation import evaluate
            from mdr_rag.core import STATE
            from mdr_rag.source_buffer import EvidenceRun, recording
            evidence_run = EvidenceRun(STATE, "evaluate")
            with recording(evidence_run.recorder):
                evaluate(args.gold, args.ks, args.out, methods=args.methods, compare_all=args.compare_all, run_id=args.run_id)
            evidence_run.save()
        elif args.command == "graph":
            from mdr_rag.graph_viz import graph_from_assessment
            graph_from_assessment(args.assessment, args.out, args.max_requirements)
    except ConnectionError:
        # SDK connection errors can contain arbitrary endpoint/response text.
        print("ERROR: missing_model", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, FileNotFoundError, FileExistsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
