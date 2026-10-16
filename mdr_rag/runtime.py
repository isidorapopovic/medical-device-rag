"""Run-scoped, durable usage guards and bounded transient-only retries."""
import time
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from random import random
from threading import Event
from typing import Callable, Iterator, TypeVar
from uuid import uuid4

from .errors import BudgetExceeded, Cancelled, CircuitOpen, FoundationError, StorageError, TransientModelError
from .run_store import RunStore
from .settings import Settings, load_settings
from .telemetry import emit, project_hash

T = TypeVar("T")
ACTIVE_RUN: ContextVar["RunContext | _LazyRun | None"] = ContextVar("foundation_run", default=None)


def error_code(error: BaseException) -> str:
    if isinstance(error, FoundationError):
        return error.code
    return "missing_model" if isinstance(error, ConnectionError) else "execution_error"


class RunContext:
    def __init__(self, settings: Settings, *, store: RunStore | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] | None = None,
                 jitter: Callable[[], float] = random):
        self.settings, self.clock, self.jitter = settings, clock, jitter
        self.cancel_event = Event()
        self.sleep = sleep or self.cancel_event.wait
        self.started = clock()
        self.id, self.project_hash = str(uuid4()), project_hash(str(settings.root))
        self.store = store or RunStore(settings.database_path, settings.sqlite_timeout_seconds)
        self.owns_store = store is None
        self.failures = 0
        self.blocked = False
        self.error_code: str | None = None
        try:
            self.store.create_run(self.id, self.project_hash, datetime.now(timezone.utc).isoformat(), settings)
            self.logger = logging.Logger("mdr_rag.run." + self.id, level=getattr(logging, settings.log_level))
            self.log_handler = logging.FileHandler(settings.database_path.with_suffix(".jsonl"), encoding="utf-8")
            self.logger.addHandler(self.log_handler)
        except BaseException as exc:
            if self.owns_store:
                self.store.close()
            if isinstance(exc, OSError):
                raise StorageError() from None
            raise

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((self.clock() - self.started) * 1000))

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()
        if self.blocked or self.clock() - self.started >= self.settings.run_timeout_seconds:
            raise BudgetExceeded()
        if self.failures >= self.settings.circuit_failure_limit:
            raise CircuitOpen()

    def call(self, stage: str, operation: Callable[[float], T], *, input_tokens: int,
             output_tokens: int, prompt_chars: int, source_counts: int = 0) -> T:
        try:
            return self._call(stage, operation, input_tokens=input_tokens, output_tokens=output_tokens,
                              prompt_chars=prompt_chars, source_counts=source_counts)
        except BaseException as exc:
            self.blocked = True
            self.error_code = error_code(exc)
            raise

    def _call(self, stage: str, operation: Callable[[float], T], *, input_tokens: int,
              output_tokens: int, prompt_chars: int, source_counts: int = 0) -> T:
        if prompt_chars > self.settings.max_prompt_chars_per_call:
            raise BudgetExceeded()
        for attempt in range(self.settings.max_retries + 1):
            self.check()
            reservation_id = str(uuid4())
            self.store.reserve(self.id, reservation_id, input_tokens, output_tokens, 0)
            remaining = self.settings.run_timeout_seconds - (self.clock() - self.started)
            timeout = min(self.settings.model_request_timeout_seconds, remaining)
            started = self.clock()
            emit(self.id, self.project_hash, stage, outcome="started", source_counts=source_counts, logger=self.logger)
            try:
                result = operation(timeout)
                duration = self.clock() - started
                if duration >= timeout:
                    raise TransientModelError()
            except BaseException as exc:
                self.store.reconcile(reservation_id, None, None, outcome="failed")
                code = error_code(exc)
                emit(self.id, self.project_hash, stage, outcome="failed", error_code=code,
                     elapsed_ms=max(0, int((self.clock() - started) * 1000)), logger=self.logger)
                if not isinstance(exc, TransientModelError):
                    raise
                self.failures += 1
                if attempt == self.settings.max_retries:
                    raise
                self.check()
                delay = min(self.settings.retry_max_seconds,
                            self.settings.retry_base_seconds * 2 ** attempt * (1 + self.jitter()))
                if delay >= self.settings.run_timeout_seconds - (self.clock() - self.started):
                    raise BudgetExceeded() from None
                emit(self.id, self.project_hash, stage, outcome="retry", error_code=exc.code, logger=self.logger)
                self.sleep(delay)
                continue
            # Only nonnegative integer counters from a completed response are metered.
            def count(key: str) -> int | None:
                value = result.get(key) if hasattr(result, "get") else None
                return value if type(value) is int and value >= 0 else None
            measured_input, measured_output = count("prompt_eval_count"), count("eval_count")
            if stage == "embedding":
                measured_output = 0
            self.store.reconcile(reservation_id, measured_input, measured_output)
            # A provider exceeding its per-call output reservation is an error even
            # if there is unused run budget. Do not publish its response.
            if measured_output is not None and measured_output > output_tokens:
                self.blocked = True
                raise BudgetExceeded()
            self.failures = 0
            self.check()
            emit(self.id, self.project_hash, stage, outcome="completed",
                 elapsed_ms=max(0, int(duration * 1000)), usage=self.store.usage(self.id), logger=self.logger)
            return result
        raise AssertionError("Unreachable bounded retry loop")

    def finish(self, error: BaseException | None = None) -> None:
        code = error_code(error) if error else self.error_code
        blocked = error is not None or self.blocked
        self.store.finish(self.id, "blocked" if blocked else "completed_with_gaps", code, self.elapsed_ms)
        emit(self.id, self.project_hash, "run", outcome="blocked" if blocked else "completed",
             error_code=code, elapsed_ms=self.elapsed_ms, usage=self.store.usage(self.id), logger=self.logger)

    def close(self) -> None:
        self.log_handler.close()
        self.logger.removeHandler(self.log_handler)
        if self.owns_store:
            self.store.close()


@contextmanager
def run_scope(settings: Settings | None = None, **kwargs) -> Iterator[RunContext]:
    current = ACTIVE_RUN.get()
    if isinstance(current, _LazyRun):
        current = current.resolve()
    if current is not None:
        yield current
        return
    run = RunContext(settings or load_settings(), **kwargs)
    token = ACTIVE_RUN.set(run)
    try:
        yield run
    except BaseException as exc:
        run.finish(exc)
        raise
    else:
        run.finish()
    finally:
        ACTIVE_RUN.reset(token)
        run.close()


def managed_run(function):
    """Lazy scope: help, file inspection and fully mocked runs create no ledger."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        existing = ACTIVE_RUN.get()
        if existing is not None:
            return function(*args, **kwargs)
        lazy = _LazyRun()
        token = ACTIVE_RUN.set(lazy)
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            if lazy.run is not None:
                lazy.run.finish(exc)
            raise
        else:
            if lazy.run is not None:
                lazy.run.finish()
            return result
        finally:
            ACTIVE_RUN.reset(token)
            if lazy.run is not None:
                lazy.run.close()
    return wrapper


class _LazyRun:
    def __init__(self):
        self.run: RunContext | None = None
        self.started = time.monotonic()

    def resolve(self) -> RunContext:
        if self.run is None:
            self.run = RunContext(load_settings())
            self.run.started = self.started
        return self.run


@contextmanager
def provider_scope() -> Iterator[RunContext]:
    current = ACTIVE_RUN.get()
    if isinstance(current, _LazyRun):
        current = current.resolve()
    if current is None:
        with run_scope() as run:
            yield run
        return
    try:
        yield current
    except BaseException as exc:
        current.blocked = True
        current.error_code = error_code(exc)
        raise
