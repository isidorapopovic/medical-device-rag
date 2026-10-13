"""Explicit provisioning only: python -m mdr_rag.download_reranker."""
import json
from .reranking import cache_folder, cross_encoder_settings, provisioned_folder


def download():
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Install requirements-rerank.txt before downloading the optional model") from exc
    settings = cross_encoder_settings()
    # local_dir avoids symlink privileges on Windows. Keep it separate from
    # Hub's cache so copying an already cached file never copies onto itself.
    destination = provisioned_folder(settings)
    path = snapshot_download(settings["model"], revision=settings["revision"], cache_dir=str(cache_folder()),
        local_dir=str(destination), max_workers=1,
        token=False, allow_patterns=["model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json",
                                    "special_tokens_map.json", "sentencepiece.bpe.model", "README.md"])
    (destination / "provision.json").write_text(json.dumps({"model": settings["model"], "revision": settings["revision"]}))
    print(f"Cached {settings['model']} revision {settings['revision']} at {path}")
    return path


if __name__ == "__main__":
    download()
