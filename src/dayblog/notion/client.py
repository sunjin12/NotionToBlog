"""Notion API client — rate-limited + 429-retrying wrapper over ``notion-client``.

Design choices (domain-notes §7):
- Token bucket at 2.5 req/s (below Notion's 3 req/s average cap) — safe margin
  eliminates flaky 429 bursts under normal operation.
- On 429 responses the wrapper honors ``Retry-After`` (up to 3 retries, then raises).
- The raw client is injected via ``raw=`` for tests — no dependency on
  ``notion-client`` at import time, so the core renderer tests stay hermetic.
- Duck-typed 429 detection (``getattr(err, "status", None) == 429``) keeps the
  retry loop decoupled from ``notion-client``'s error hierarchy.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_RATE_RPS = 2.5
DEFAULT_MAX_RETRIES = 3


@dataclass
class TokenBucket:
    """Simple monotonic-clock token bucket. 1 unit = 1 request."""

    rate_rps: float
    capacity: float
    _tokens: float
    _last: float
    clock: Callable[[], float]
    sleep: Callable[[float], None]

    @classmethod
    def create(
        cls,
        rate_rps: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> TokenBucket:
        capacity = max(1.0, rate_rps)
        return cls(
            rate_rps=rate_rps,
            capacity=capacity,
            _tokens=capacity,
            _last=clock(),
            clock=clock,
            sleep=sleep,
        )

    def acquire(self) -> None:
        now = self.clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate_rps)
        self._last = now
        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self.rate_rps
            self.sleep(wait)
            self._tokens = 0.0
            self._last = self.clock()
            return
        self._tokens -= 1.0


class NotionClient:
    """Rate-limited wrapper exposing just the endpoints Dayblog needs.

    ``raw`` must look like the ``notion_client.Client`` surface: it must have
    ``databases.retrieve``, ``data_sources.query``, ``pages.retrieve``, and
    ``blocks.children.list`` callables. Pagination is handled automatically;
    callers receive the fully materialized result list.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        raw: Any = None,
        rate_rps: float = DEFAULT_RATE_RPS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if raw is None:
            if token is None:
                raise ValueError("Either `token` or `raw` must be provided")
            from notion_client import Client  # lazy — keeps renderer tests hermetic

            raw = Client(auth=token)
        self._raw = raw
        self._limiter = TokenBucket.create(rate_rps, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._max_retries = max_retries
        self._data_source_ids: dict[str, str] = {}

    def query_database(
        self,
        database_id: str,
        *,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
    ) -> list[dict]:
        """Query a Notion database and return every page (paginated under the hood).

        Notion's 2025-09-03 API split databases into containers + data sources
        and ``notion-client`` 3.x moved ``query`` onto ``data_sources``. The
        ``data_source_id`` is not the same as the ``database_id`` on any DB
        created (or restructured) after the split, so we resolve it once via
        ``databases.retrieve`` and cache per-database-id for the process.
        """
        data_source_id = self._resolve_data_source_id(database_id)
        return self._paginate(
            lambda **cursor: self._request(
                self._raw.data_sources.query,
                data_source_id=data_source_id,
                filter=filter,
                sorts=sorts,
                **cursor,
            )
        )

    def _resolve_data_source_id(self, database_id: str) -> str:
        cached = self._data_source_ids.get(database_id)
        if cached is not None:
            return cached
        db = self._request(self._raw.databases.retrieve, database_id=database_id)
        sources = db.get("data_sources") or []
        if not sources:
            raise RuntimeError(
                f"Notion DB {database_id} exposes no data_sources — expected at least one under API 2025-09-03"
            )
        resolved = sources[0]["id"]
        self._data_source_ids[database_id] = resolved
        return resolved

    def retrieve_page(self, page_id: str) -> dict:
        return self._request(self._raw.pages.retrieve, page_id=page_id)

    def list_children(self, block_id: str) -> list[dict]:
        return self._paginate(
            lambda **cursor: self._request(
                self._raw.blocks.children.list,
                block_id=block_id,
                **cursor,
            )
        )

    # --- internals ------------------------------------------------------------

    def _paginate(self, call: Callable[..., dict]) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        while True:
            kw = {"start_cursor": cursor} if cursor else {}
            resp = call(**kw)
            items.extend(resp.get("results", []))
            if not resp.get("has_more"):
                return items
            cursor = resp.get("next_cursor")
            if cursor is None:
                return items

    def _request(self, fn: Callable[..., dict], **kw: Any) -> dict:
        # Drop None kwargs so notion-client doesn't reject unexpected nulls.
        kw = {k: v for k, v in kw.items() if v is not None}
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                return fn(**kw)
            except Exception as exc:
                if _is_rate_limited(exc) and attempt < self._max_retries:
                    self._sleep(_retry_after(exc))
                    continue
                raise


def _is_rate_limited(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 429 or getattr(exc, "code", None) == "rate_limited"


def _retry_after(exc: Exception, default: float = 1.0) -> float:
    headers = getattr(exc, "headers", None) or {}
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            return float(raw)
    except (AttributeError, ValueError, TypeError):
        pass
    explicit = getattr(exc, "retry_after", None)
    if explicit is not None:
        try:
            return float(explicit)
        except (ValueError, TypeError):
            pass
    return default
