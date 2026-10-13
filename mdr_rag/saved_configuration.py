"""Saved settings govern continuation; explicit overrides remain scoped."""
import os
from contextlib import contextmanager

ENV_FIELDS = {
    "ollama_gpu_layers": "OLLAMA_NUM_GPU",
    "retrieval_mode": "RETRIEVAL_MODE", "llm_model": "OLLAMA_LLM_MODEL",
    "embedding_model": "EMBEDDING_MODEL", "num_ctx": "OLLAMA_NUM_CTX",
    "multi_query_enabled": "MULTI_QUERY_ENABLED", "query_planner": "QUERY_PLANNER",
    "multi_query_max": "MULTI_QUERY_MAX", "retrieval_per_query": "RETRIEVAL_PER_QUERY",
    "retrieval_max_candidates": "RETRIEVAL_MAX_CANDIDATES", "reranker_backend": "RERANK_BACKEND",
    "gate_mode": "EVIDENCE_GATE_MODE", "gate_threshold": "EVIDENCE_GATE_THRESHOLD",
    "cross_encoder_cache": "CROSS_ENCODER_CACHE",
}


def environment(config):
    result = {}
    for key, name in ENV_FIELDS.items():
        if key in config:
            value = config[key]
            result[name] = str(value).lower() if isinstance(value, bool) else str(value) if value is not None else ""
    backend = config.get("reranker_backend", "none")
    result["RERANK_ENABLED"] = "false" if backend == "none" else "true"
    identity = config.get("reranker_identity", {})
    if backend == "cross_encoder":
        for key, name in {"model": "CROSS_ENCODER_MODEL", "revision": "CROSS_ENCODER_REVISION",
                          "max_tokens": "CROSS_ENCODER_MAX_TOKENS", "batch_size": "CROSS_ENCODER_BATCH_SIZE"}.items():
            if key in identity:
                result[name] = str(identity[key])
    # Artifact contents are pinned in state; current environment paths must not
    # silently replace them during a saved-state continuation.
    result["EVIDENCE_GATE_CALIBRATION"] = ""
    return result


@contextmanager
def scoped_environment(values):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve(saved, k, overrides, use_env, build):
    overrides = overrides or {}
    unknown = set(overrides) - set(ENV_FIELDS)
    if unknown:
        raise ValueError(f"Unknown configuration overrides: {sorted(unknown)}")
    values = environment(saved) if saved and not use_env else {}
    for key, value in overrides.items():
        values[ENV_FIELDS[key]] = str(value).lower() if isinstance(value, bool) else str(value)
    with scoped_environment(values):
        config = build(k)
    if saved and not use_env:
        from .evidence_gate import Calibration
        if config["gate_mode"] == "strict" and saved.get("gate_calibration") is not None:
            artifact = Calibration.model_validate(saved["gate_calibration"])
            if saved.get("calibration") != artifact.fingerprint:
                raise ValueError("Saved calibration identity mismatch; preserve state and investigate")
            config.update(gate_calibration=artifact.model_dump(), calibration=artifact.fingerprint)
    return config
