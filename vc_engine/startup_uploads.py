"""Local capped uploads and label-only extraction; no model/OCR/network."""
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from .models import ROOT, clean
from .startup_profile import PROFILE_FIELDS, profile_from_dict, profile_payload

LABELS = {key.replace("_", " "): key for key in PROFILE_FIELDS}
LABELS.update({"startup name": "name", "company name": "name", "intended purpose": "intended_use"})
DEFAULT_UPLOADS = ROOT / "data/vc/uploads"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def ingest_startup_upload(filename: str, content: bytes, *, root: str | Path = DEFAULT_UPLOADS) -> dict:
    if not filename or any(character in filename for character in ("/", "\\", "\0")) or filename in {".", ".."}:
        raise ValueError("Upload must have a plain filename without path components")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".json"}:
        raise ValueError("Startup uploads support PDF, DOCX or JSON")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Startup upload must contain 1 byte to 20 MiB")
    digest = hashlib.sha256(content).hexdigest()
    warnings, extraction = [], None
    if suffix == ".json":
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("Startup JSON exceeds 2 MiB")
        profile = profile_from_dict(json.loads(content.decode("utf-8-sig")), input_sha256=digest)
        status = "structured_json"
    else:
        from mdr_rag.document_parsers import parse_document
        extraction = parse_document(content, suffix, ocr_enabled=False)
        status = extraction.status
        sources, values = [], {key: [] for key in PROFILE_FIELDS}
        text_budget = 1000000
        for unit in extraction.units[:100]:
            if not unit.raw_text.strip() or text_budget <= 0:
                continue
            text = unit.raw_text[:min(text_budget, 100000)]
            text_budget -= len(text)
            sid = f"upload:{digest}:unit:{unit.index}"
            sources.append(dict(source_id=sid, text=text, page=unit.physical_page,
                chunk=f"{filename}: unit {unit.index}", origin="pitch_deck"))
            for line in text.splitlines():
                match = re.match(r"^\s*([A-Za-z _/]+)\s*:\s*(.+)$", line)
                key = LABELS.get(clean(match[1]).lower().replace("_", " ")) if match else None
                if key and len(line) <= 1000:
                    values[key].append((clean(match[2]), sid, line))
        payload = {"sources": sources, "field_evidence": []}
        for key, matches in values.items():
            unique = {match[0] for match in matches}
            payload[key] = next(iter(unique)) if len(unique) == 1 else None
            if len(unique) > 1:
                warnings.append(f"Conflicting labelled values for {key}; left unknown for review.")
            if payload[key]:
                payload["field_evidence"].extend(dict(field=key, source_id=sid, quote=quote) for _, sid, quote in matches)
        if len(payload["field_evidence"]) > 100:
            payload["field_evidence"] = payload["field_evidence"][:100]
            warnings.append("Field anchor cap reached; review the original deck.")
        profile = profile_from_dict(payload, input_sha256=digest)
        warnings += ["Label-only draft extraction; unlabeled or conflicting facts stay unknown. Pitch claims are not independent verification."]
        if len(extraction.units) > 100 or text_budget <= 0:
            warnings.append("Source extraction profile coverage was capped; inspect the original file.")
        if status != "parsed":
            warnings.append("Document extraction is " + status + "; inspect diagnostics and provide structured JSON if needed.")
    destination = Path(root).resolve() / ("upload-" + digest[:12] + "-" + uuid4().hex[:12])
    destination.mkdir(parents=True, exist_ok=False)
    (destination / ("original" + suffix)).write_bytes(content)
    (destination / "profile.json").write_text(json.dumps(profile_payload(profile), ensure_ascii=False, indent=2), encoding="utf-8")
    if extraction:
        (destination / "extraction.json").write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
    metadata = dict(original_filename=filename, sha256=digest, status=status, warnings=warnings)
    (destination / "manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return dict(profile=profile, directory=destination, **metadata)
