"""Validated local settings; no clients, filesystem writes or dotenv mutation on import."""
import os
import unicodedata
from pathlib import Path
from typing import Literal, Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)
    root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    database_path: Path = Path("state/runtime.sqlite3")
    llm_provider: Literal["ollama", "cloud"] = "ollama"
    cloud_llm_enabled: bool = False
    cloud_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_llm_model: str = "qwen3:4b"
    embedding_model: str = "embeddinggemma"
    embedding_revision: str = Field(default="", max_length=200)
    ollama_num_ctx: int = Field(default=8192, gt=0)
    ollama_num_gpu: int | None = Field(default=None, ge=0)
    retrieval_mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    rerank_enabled: bool = False
    rerank_backend: Literal["none", "llm", "cross_encoder"] | None = None
    multi_query_enabled: bool = True
    query_planner: Literal["deterministic", "llm"] = "deterministic"
    multi_query_max: int = Field(default=4, ge=1, le=4)
    retrieval_per_query: int = Field(default=12, ge=1, le=12)
    retrieval_max_candidates: int = Field(default=30, ge=1, le=30)
    evidence_gate_mode: Literal["strict", "experimental", "disabled"] = "strict"
    evidence_gate_threshold: float | None = Field(default=None, allow_inf_nan=False)
    evidence_gate_calibration: Path | None = None
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    cross_encoder_revision: str = Field(default="2cfc18c9415c912f9d8155881c133215df768a70", pattern=r"^[a-f0-9]{40}$")
    cross_encoder_max_tokens: int = Field(default=512, ge=32, le=512)
    cross_encoder_batch_size: int = Field(default=4, ge=1, le=4)
    cross_encoder_cache: Path = Path("reports/reranker-cache")
    legal_version: str = Field(default="UNSPECIFIED HISTORICAL TEXT", min_length=1, max_length=255)
    ocr_enabled: bool = False
    require_human_review: Literal[True] = True
    app_host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    max_llm_calls_per_run: int = Field(default=30, ge=1)
    max_prompt_chars_per_call: int = Field(default=16000, ge=1)
    max_output_tokens_per_call: int = Field(default=1200, ge=1)
    max_run_input_tokens: int = Field(default=120000, ge=1)
    max_run_output_tokens: int = Field(default=16000, ge=1)
    max_cloud_spend_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    run_timeout_seconds: float = Field(default=1200, gt=0, allow_inf_nan=False)
    model_request_timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0, le=2)
    retry_base_seconds: float = Field(default=0.25, ge=0, le=5, allow_inf_nan=False)
    retry_max_seconds: float = Field(default=2, ge=0, le=30, allow_inf_nan=False)
    circuit_failure_limit: int = Field(default=3, ge=1, le=30)
    sqlite_timeout_seconds: float = Field(default=2, ge=0, le=30, allow_inf_nan=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("*", mode="before")
    @classmethod
    def strict_booleans(cls, value, info):
        boolean_fields = {"cloud_llm_enabled", "rerank_enabled", "ocr_enabled", "require_human_review", "multi_query_enabled"}
        if info.field_name in boolean_fields and isinstance(value, str):
            if value.casefold() not in {"true", "false"}:
                raise ValueError("Boolean setting must be true or false")
            return value.casefold() == "true"
        elif info.field_name not in boolean_fields and isinstance(value, bool):
            raise ValueError("Boolean cannot be used as a numeric or string setting")
        if info.field_name in {"ollama_num_gpu", "evidence_gate_threshold", "evidence_gate_calibration"} and value == "":
            return None
        return value

    @field_validator("ollama_llm_model", "embedding_model")
    @classmethod
    def model_name(cls, value: str) -> str:
        if not value.strip() or len(value) > 200 or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Invalid local model identifier")
        # Ollama's remote model suffix must never activate cloud implicitly.
        if value.casefold().endswith(":cloud") or value.casefold().endswith("-cloud"):
            raise ValueError("Remote Ollama models are disabled")
        return unicodedata.normalize("NFC", value.strip())

    @model_validator(mode="after")
    def safety(self):
        host = urlsplit(self.ollama_host)
        if host.port is not None and not 1 <= host.port <= 65535:
            raise ValueError("Invalid loopback port")
        if (host.scheme != "http" or host.hostname not in {"localhost", "127.0.0.1", "::1"}
                or host.username or host.password or host.path not in {"", "/"} or host.query or host.fragment):
            raise ValueError("Ollama must use a loopback HTTP endpoint")
        if self.llm_provider == "cloud" and (not self.cloud_llm_enabled or not self.cloud_api_key
                                             or not self.cloud_api_key.get_secret_value().strip()):
            raise ValueError("Cloud provider requires explicit opt-in and credentials")
        if self.evidence_gate_mode == "experimental" and self.evidence_gate_threshold is None:
            raise ValueError("Experimental gating requires an explicit threshold")
        root = self.root.expanduser().resolve()
        database = self.database_path.expanduser()
        database = (root / database).resolve() if not database.is_absolute() else database.resolve()
        if not database.is_relative_to(root):
            raise ValueError("Run database must stay inside the project root")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "database_path", database)
        for name in ("cross_encoder_cache", "evidence_gate_calibration"):
            path = getattr(self, name)
            if path is not None:
                path = path.expanduser()
                object.__setattr__(self, name, (root / path).resolve() if not path.is_absolute() else path.resolve())
        return self

    def safe_dump(self) -> dict:
        """Deliberately exclude paths, arbitrary model IDs, hosts and all credentials."""
        private_fields = {"root", "database_path", "cloud_api_key", "ollama_host", "ollama_llm_model",
                          "embedding_model", "embedding_revision", "cross_encoder_cache", "evidence_gate_calibration", "legal_version",
                          "cross_encoder_model", "cross_encoder_revision"}
        return self.model_dump(exclude=private_fields, mode="json")


def load_settings(root: Path | None = None, *, environ: Mapping[str, str] | None = None,
                  env_file: Path | None = None) -> Settings:
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    # No ${...} expansion from unrelated ambient variables into file settings.
    values = dict(dotenv_values(env_file or root / ".env", interpolate=False))
    values.update(os.environ if environ is None else environ)
    fields = {name.upper(): name for name in Settings.model_fields if name != "root"}
    fields["RUNTIME_DATABASE"] = "database_path"
    # Preserve established env spelling and explicit backend precedence.
    if "RERANK_ENABLED" not in values and "RERANKER_ENABLED" in values:
        values["RERANK_ENABLED"] = values["RERANKER_ENABLED"]
    selected = {fields[key]: value for key, value in values.items() if key in fields and value is not None}
    if selected.get("rerank_backend") == "":
        selected.pop("rerank_backend")
    return Settings(root=root, **selected)
