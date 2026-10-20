"""Opt-in, bounded openFDA transport with persistent response caching."""
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

from .regulatory_models import FDA_ENDPOINT, FetchLimits, utc_now
from .regulatory_store import FDAStore


class FDAError(RuntimeError):
    pass


@dataclass(frozen=True)
class FDAPage:
    payload: dict
    source_url: str
    fetched_at: str
    live: bool
    stale: bool = False


class FDAClient:
    """Construction never requests data. No automatic fallback on live errors."""
    def __init__(self, store: FDAStore, *, online: bool = False, refresh: bool = False,
                 limits: FetchLimits = FetchLimits(), session=None, sleeper=time.sleep,
                 monotonic=time.monotonic):
        limits.validate()
        if refresh and not online:
            raise ValueError("--refresh requires --online")
        self.store, self.online, self.refresh, self.limits = store, online, refresh, limits
        self.session, self.sleeper, self.monotonic = session, sleeper, monotonic
        self.requests_made = 0
        self.checked_urls: list[str] = []
        self._last_request = None
        self._owns_session = False

    def page(self, expression: str, *, size: int, skip: int) -> FDAPage:
        if not 1 <= size <= min(1000, self.limits.page_size) or not 0 <= skip <= 25000:
            raise ValueError("Invalid FDA page size/offset")
        parameters = dict(search=expression, limit=size, skip=skip, sort="decision_date:desc")
        cached = self.store.page(parameters)
        if cached and not self.refresh:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
            except (ValueError, TypeError):
                age = float("inf")
            stale = not 0 <= age <= self.limits.cache_hours * 3600
            if not self.online or not stale:
                return FDAPage(json.loads(cached["raw_json"]), cached["source_url"], cached["fetched_at"], False, stale)
        if not self.online:
            raise FDAError("No cached FDA response. Network is disabled; use --online explicitly.")
        source_url = FDA_ENDPOINT + "?" + urlencode(parameters)
        payload = self._request(parameters)
        return FDAPage(payload, source_url, utc_now(), True)

    def _request(self, parameters: dict) -> dict:
        # Lazy dependency: Task 01 and all offline modes still work with python -S.
        import requests

        if self.session is None:
            self.session = requests.Session()
            self._owns_session = True
        transient = {429, 500, 502, 503, 504}
        max_requests = self.limits.max_pages * (self.limits.retries + 1)
        for attempt in range(self.limits.retries + 1):
            if self.requests_made >= max_requests:
                raise FDAError("FDA request cap reached")
            if self._last_request is not None:
                self.sleeper(max(0, self.limits.min_interval - (self.monotonic() - self._last_request)))
            self.requests_made += 1
            self._last_request = self.monotonic()
            response = None
            try:
                response = self.session.get(FDA_ENDPOINT, params=parameters,
                    timeout=(min(5, self.limits.timeout), self.limits.timeout), allow_redirects=False,
                    stream=True, headers={"User-Agent": "medical-device-rag-vc/0.2 (510k research)", "Accept": "application/json"})
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise FDAError("FDA response exceeds 4 MiB cap")
                    chunks.append(chunk)
                try:
                    payload = json.loads(b"".join(chunks).decode("utf-8"))
                except (ValueError, UnicodeError):
                    payload = None
                status = response.status_code
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                code = error.get("code") if isinstance(error, dict) else None
                if status == 404 and code == "NOT_FOUND":
                    return {"meta": {"results": {"total": 0}}, "results": [], "error": error}
                if status == 200:
                    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list) or error:
                        raise FDAError("Invalid FDA response: expected a results array without API errors")
                    return payload
                message = error.get("message", "Request failed") if isinstance(error, dict) else "Request failed"
                if status not in transient or attempt == self.limits.retries:
                    raise FDAError(f"openFDA HTTP {status}: {str(message)[:300]}")
                wait = self.limits.backoff * 2 ** attempt
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        requested_wait = float(retry_after)
                    except ValueError:
                        raise FDAError("FDA Retry-After is not numeric; retry later") from None
                    if not 0 <= requested_wait <= 10:
                        raise FDAError("FDA Retry-After exceeds bounded wait; retry later")
                    wait = max(wait, requested_wait)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.limits.retries:
                    raise FDAError("FDA timeout/connection failure after bounded retries; cached data was not relabeled live") from None
                wait = self.limits.backoff * 2 ** attempt
            except requests.RequestException:
                raise FDAError("FDA transport failed; cached data remains unchanged") from None
            finally:
                if response is not None:
                    response.close()
            self.sleeper(wait)
        raise FDAError("FDA request failed")

    def close(self):
        if self._owns_session and self.session is not None:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
