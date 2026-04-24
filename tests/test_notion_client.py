"""Tests for the rate-limited + retrying Notion client wrapper.

All tests use fake ``raw`` objects; no ``notion-client`` import occurs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from dayblog.notion.client import NotionClient, TokenBucket


# --- fakes --------------------------------------------------------------------


class FakeClock:
    """Deterministic monotonic clock; every sleep advances the clock."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class _Endpoint:
    responses: list[Any] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def __call__(self, **kw: Any) -> Any:
        self.calls.append(kw)
        if not self.responses:
            raise AssertionError("no canned response queued")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@dataclass
class FakeRaw:
    databases_query: _Endpoint = field(default_factory=_Endpoint)
    pages_retrieve: _Endpoint = field(default_factory=_Endpoint)
    blocks_children_list: _Endpoint = field(default_factory=_Endpoint)

    class _Databases:
        def __init__(self, ep: _Endpoint) -> None:
            self.query = ep

    class _Pages:
        def __init__(self, ep: _Endpoint) -> None:
            self.retrieve = ep

    class _Blocks:
        def __init__(self, ep: _Endpoint) -> None:
            self.children = type("C", (), {"list": ep})()

    def __post_init__(self) -> None:
        self.databases = self._Databases(self.databases_query)
        self.pages = self._Pages(self.pages_retrieve)
        self.blocks = self._Blocks(self.blocks_children_list)


class FakeApiError(Exception):
    def __init__(self, status: int, retry_after: float | None = None) -> None:
        self.status = status
        self.headers = {"Retry-After": str(retry_after)} if retry_after else {}


# --- helpers ------------------------------------------------------------------


def _make_client(raw: FakeRaw, *, rate_rps: float = 100.0, max_retries: int = 3) -> tuple[NotionClient, FakeClock]:
    clock = FakeClock()
    client = NotionClient(
        raw=raw,
        rate_rps=rate_rps,
        max_retries=max_retries,
        clock=clock,
        sleep=clock.sleep,
    )
    return client, clock


# --- token bucket -------------------------------------------------------------


def test_token_bucket_sleeps_when_tokens_exhausted():
    clock = FakeClock()
    bucket = TokenBucket.create(2.5, clock=clock, sleep=clock.sleep)
    # First 2 calls consume capacity (2.5 → 1.5 → 0.5). Third call triggers sleep.
    bucket.acquire()
    bucket.acquire()
    assert clock.sleeps == []
    bucket.acquire()
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx((1.0 - 0.5) / 2.5, rel=1e-3)


def test_token_bucket_refills_over_time():
    clock = FakeClock()
    bucket = TokenBucket.create(2.5, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        bucket.acquire()
    # Advance clock by 1s: +2.5 tokens, capped at capacity. Next acquire shouldn't sleep.
    clock.now += 1.0
    prior_sleeps = len(clock.sleeps)
    bucket.acquire()
    assert len(clock.sleeps) == prior_sleeps


# --- retrieve / pagination ----------------------------------------------------


def test_retrieve_page_passes_page_id():
    raw = FakeRaw()
    raw.pages_retrieve.responses = [{"id": "abc"}]
    client, _ = _make_client(raw)
    assert client.retrieve_page("abc") == {"id": "abc"}
    assert raw.pages_retrieve.calls == [{"page_id": "abc"}]


def test_query_database_paginates_until_exhausted():
    raw = FakeRaw()
    raw.databases_query.responses = [
        {"results": [{"id": "1"}, {"id": "2"}], "has_more": True, "next_cursor": "c1"},
        {"results": [{"id": "3"}], "has_more": False, "next_cursor": None},
    ]
    client, _ = _make_client(raw)
    result = client.query_database("db-1")
    assert [r["id"] for r in result] == ["1", "2", "3"]
    assert raw.databases_query.calls[0] == {"database_id": "db-1"}
    assert raw.databases_query.calls[1]["start_cursor"] == "c1"


def test_list_children_paginates():
    raw = FakeRaw()
    raw.blocks_children_list.responses = [
        {"results": [{"id": "b1"}], "has_more": True, "next_cursor": "k"},
        {"results": [{"id": "b2"}], "has_more": False, "next_cursor": None},
    ]
    client, _ = _make_client(raw)
    result = client.list_children("parent-id")
    assert [r["id"] for r in result] == ["b1", "b2"]


# --- 429 retry ----------------------------------------------------------------


def test_request_retries_on_429_and_honors_retry_after():
    raw = FakeRaw()
    raw.pages_retrieve.responses = [
        FakeApiError(status=429, retry_after=2.0),
        FakeApiError(status=429, retry_after=1.5),
        {"id": "ok"},
    ]
    client, clock = _make_client(raw, rate_rps=1000.0)
    result = client.retrieve_page("ok")
    assert result == {"id": "ok"}
    assert clock.sleeps == [2.0, 1.5]


def test_request_raises_after_max_retries_exceeded():
    raw = FakeRaw()
    raw.pages_retrieve.responses = [FakeApiError(status=429, retry_after=0.1)] * 5
    client, _ = _make_client(raw, rate_rps=1000.0, max_retries=2)
    with pytest.raises(FakeApiError):
        client.retrieve_page("x")
    # 3 attempts total (initial + 2 retries)
    assert len(raw.pages_retrieve.calls) == 3


def test_request_does_not_retry_non_429_errors():
    raw = FakeRaw()
    raw.pages_retrieve.responses = [FakeApiError(status=404)]
    client, _ = _make_client(raw, rate_rps=1000.0)
    with pytest.raises(FakeApiError):
        client.retrieve_page("missing")
    assert len(raw.pages_retrieve.calls) == 1


def test_notion_client_requires_token_or_raw():
    with pytest.raises(ValueError, match="token.*raw"):
        NotionClient()
