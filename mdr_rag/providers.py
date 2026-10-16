"""Injectable local provider contracts and guarded legacy transport adapters."""
import json
import math
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError as PydanticValidationError

from .errors import MissingModel, ParsingError, TransientModelError, ValidationError
from .runtime import provider_scope

M = TypeVar("M", bound=BaseModel)


class LLMProvider(Protocol):
    def generate(self, instructions: str, input_text: str, model_type: type[M]) -> M: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _transport(operation: str, timeout: float, host: str, kwargs: dict):
    """SDK clients are created only at IO; legacy injected module callables still work."""
    import httpx
    import ollama
    function = getattr(ollama, operation)
    if not hasattr(ollama, "Client"):
        # Existing integrations may inject a minimal module fake, rather than
        # patching a method on the installed SDK. It is an explicit test seam.
        return function(**kwargs)
    try:
        # Module helpers are bound to the SDK's default client. Replace that
        # default only for real transport; injected callable fakes need no client.
        if isinstance(getattr(function, "__self__", None), ollama.Client):
            client = ollama.Client(host=host, timeout=httpx.Timeout(timeout), trust_env=False,
                                   follow_redirects=False)
            try:
                return getattr(client, operation)(**kwargs)
            finally:
                client._client.close()
        return function(**kwargs)
    except ollama.ResponseError as exc:
        if exc.status_code == 404:
            raise MissingModel() from None
        if exc.status_code in {408, 429, 500, 502, 503, 504}:
            raise TransientModelError() from None
        raise ValidationError() from None
    except httpx.TransportError:
        raise TransientModelError() from None
    except ConnectionError:
        # Historical direct call API propagates ConnectionError, without retries.
        # CLI sanitizes it; telemetry never logs exception bodies.
        raise


def guarded_request(operation: str, kwargs: dict, *, stage: str, transport: Callable = _transport):
    with provider_scope() as run:
        settings = run.settings
        if settings.llm_provider != "ollama":
            raise ValidationError()  # No cloud implementation or implicit fallback.
        if operation not in {"chat", "embed"}:
            raise ValidationError()
        expected_model = settings.ollama_llm_model if operation == "chat" else settings.embedding_model
        if kwargs.get("model") != expected_model:
            raise ValidationError()
        if operation == "chat":
            kwargs = dict(kwargs, options={**kwargs.get("options", {}),
                                         "num_ctx": settings.ollama_num_ctx,
                                         "num_predict": settings.max_output_tokens_per_call})
            prompt_chars = sum(len(item["content"]) for item in kwargs["messages"])
            output_tokens = settings.max_output_tokens_per_call
            source_counts = 0
        else:
            prompt_chars = sum(len(text) for text in kwargs["input"])
            output_tokens, source_counts = 0, len(kwargs["input"])
        # Bytes plus serialized schema/framing allowance are a conservative
        # estimate, not measured model-token counts. Never estimate len/4.
        input_tokens = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 256
        return run.call(stage, lambda timeout: transport(operation, timeout, settings.ollama_host, kwargs),
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        prompt_chars=prompt_chars, source_counts=source_counts)


class OllamaProvider:
    def generate(self, instructions: str, input_text: str, model_type: type[M]) -> M:
        with provider_scope() as run:
            device = {"num_gpu": run.settings.ollama_num_gpu} if run.settings.ollama_num_gpu is not None else {}
            kwargs = dict(model=run.settings.ollama_llm_model,
                          messages=[{"role": "system", "content": instructions},
                                    {"role": "user", "content": input_text}],
                          format=model_type.model_json_schema(),
                          options={"temperature": 0, "num_ctx": run.settings.ollama_num_ctx, **device}, think=False)
            result = guarded_request("chat", kwargs, stage="generation")
            try:
                return model_type.model_validate_json(result["message"]["content"])
            except (PydanticValidationError, KeyError, TypeError):
                raise ParsingError() from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValidationError()
        with provider_scope() as run:
            # Indexing's legacy 32-chunk batches may exceed the per-call prompt
            # cap. Split without truncating text; share one run/call budget.
            batches: list[list[str]] = []
            current: list[str] = []
            size = 0
            for text in texts:
                if current and size + len(text) > run.settings.max_prompt_chars_per_call:
                    batches.append(current)
                    current, size = [], 0
                current.append(text)
                size += len(text)
            if current:
                batches.append(current)
            result = []
            for batch in batches:
                kwargs = dict(model=run.settings.embedding_model, input=batch)
                if run.settings.ollama_num_gpu is not None:
                    kwargs["options"] = {"num_gpu": run.settings.ollama_num_gpu}
                response = guarded_request("embed", kwargs, stage="embedding")
                result.extend(self._vectors(response, len(batch)))
            return result

    @staticmethod
    def _vectors(response, count: int) -> list[list[float]]:
        try:
            vectors = [list(vector) for vector in response["embeddings"]]
            if (len(vectors) != count or not vectors or not vectors[0]
                    or any(len(v) != len(vectors[0]) for v in vectors)
                    or any(type(n) not in {float, int} or not math.isfinite(n) for v in vectors for n in v)):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError):
            raise ParsingError() from None


class FakeLLM:
    """Explicit synthetic responses; never fabricates a default legal finding."""
    def __init__(self, responses: list[dict]):
        self.responses = iter(responses)
        self.calls = 0

    def generate(self, instructions: str, input_text: str, model_type: type[M]) -> M:
        self.calls += 1
        return model_type.model_validate(next(self.responses))


class FakeEmbeddings:
    def __init__(self):
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), 1.0] for text in texts]
