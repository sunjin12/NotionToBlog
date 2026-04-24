"""Publish flow — Notion page → Hugo page bundle.

Orchestrates :mod:`dayblog.notion` (client, renderer, image collector) with
:mod:`dayblog.hugo` (front-matter compose/parse) behind a single
:func:`publish_page` entry point. The CLI (``python -m dayblog publish-today``)
wires the real :class:`NotionClient` + ``httpx``; tests inject a fake client
and a dict-backed ``http_get``.

Idempotency (domain-notes §2, decision #1):

- If a bundle already exists under the page's date slug and its
  ``source_notion_id`` matches this page, compare ``lastmod`` vs Notion
  ``last_edited_time``. Equal-or-newer locally → **skip**. Stale → **update**.
- If a bundle exists at that slug but has a *different* ``source_notion_id``,
  the current page gets the next free numbered slug (``-2``, ``-3``, …).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from . import hugo
from .notion.images import ImageCollector, download_all
from .notion.render import RenderContext, render_blocks

_MAX_SLUG_SUFFIX = 50


class _ClientLike(Protocol):
    def retrieve_page(self, page_id: str) -> dict: ...

    def list_children(self, block_id: str) -> list[dict]: ...


@dataclass
class PublishResult:
    path: Path
    status: str  # "created" | "updated" | "skipped"
    image_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PageMeta:
    page_id: str
    title: str
    date: date_cls
    date_iso: str  # Full ISO 8601 with KST, suitable for `date` front matter
    last_edited_time: str  # Raw Notion ISO string (UTC "...Z")
    tags: list[str]
    category: str | None
    summary: str


def publish_page(
    *,
    client: _ClientLike,
    page_id: str,
    site_root: Path,
    http_get: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> PublishResult:
    """Publish one Notion page into the Hugo site repo.

    Returns a :class:`PublishResult` describing what happened. When
    ``http_get`` is ``None`` the renderer still records image references but
    no files are downloaded — callers that only want the Markdown skip the
    HTTP client injection.
    """
    page = client.retrieve_page(page_id)
    now_dt = now or datetime.now(hugo.KST)
    meta = _extract_metadata(page, page_id=page_id, now=now_dt)

    top = client.list_children(page_id)
    collector = ImageCollector(page_id=page_id)
    ctx = RenderContext(
        page_id=page_id,
        fetch_children=client.list_children,
        collector=collector,
    )
    body = render_blocks(top, ctx)

    posts_dir = site_root.joinpath(*hugo.POSTS_SUBPATH)
    slug, existing_fm, index_path = _resolve_bundle(posts_dir, meta.date, page_id)

    if existing_fm is not None and _is_up_to_date(existing_fm, meta.last_edited_time):
        return PublishResult(
            path=index_path,
            status="skipped",
            warnings=list(ctx.warnings),
        )

    fm = _build_front_matter(meta, slug=slug, now=now_dt)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(hugo.compose_post(fm, body), encoding="utf-8")

    image_count = 0
    if http_get is not None and collector.refs:
        download_all(collector.refs, index_path.parent, http_get=http_get)
        image_count = len(collector.refs)

    return PublishResult(
        path=index_path,
        status="updated" if existing_fm is not None else "created",
        image_count=image_count,
        warnings=list(ctx.warnings),
    )


# --- Notion page → metadata --------------------------------------------------


def _extract_metadata(page: dict, *, page_id: str, now: datetime) -> _PageMeta:
    props = page.get("properties") or {}
    date_prop = props.get("Date") or {}
    if date_prop.get("type") != "date":
        raise hugo.HugoError(f"Notion page {page_id} is missing required Date property")
    raw = (date_prop.get("date") or {}).get("start")
    if not raw:
        raise hugo.HugoError(f"Notion page {page_id} has empty Date.start")

    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        date_value = dt.astimezone(hugo.KST).date()
        date_iso = dt.astimezone(hugo.KST).isoformat()
    else:
        date_value = date_cls.fromisoformat(raw)
        # Notion date-only → synthesize a time from `now` so the YAML `date`
        # is a full timestamp (Hugo archetype convention).
        date_iso = datetime(
            date_value.year, date_value.month, date_value.day,
            now.hour, now.minute, now.second,
            tzinfo=hugo.KST,
        ).isoformat()

    return _PageMeta(
        page_id=page_id,
        title=_extract_title(props.get("Title") or props.get("Name") or {}) or f"untitled-{page_id[:8]}",
        date=date_value,
        date_iso=date_iso,
        last_edited_time=page.get("last_edited_time", ""),
        tags=_extract_multi_select(props.get("Tags") or {}),
        category=_extract_select(props.get("Category") or {}),
        summary=_extract_rich_text(props.get("Summary") or {}),
    )


def _extract_title(prop: dict) -> str:
    if prop.get("type") != "title":
        return ""
    return "".join(s.get("plain_text", "") for s in prop.get("title") or [])


def _extract_multi_select(prop: dict) -> list[str]:
    if prop.get("type") != "multi_select":
        return []
    return [opt.get("name", "") for opt in prop.get("multi_select") or [] if opt.get("name")]


def _extract_select(prop: dict) -> str | None:
    if prop.get("type") != "select":
        return None
    sel = prop.get("select")
    return (sel or {}).get("name") or None


def _extract_rich_text(prop: dict) -> str:
    if prop.get("type") != "rich_text":
        return ""
    return "".join(s.get("plain_text", "") for s in prop.get("rich_text") or [])


# --- slug + idempotency ------------------------------------------------------


def _resolve_bundle(
    posts_dir: Path, date: date_cls, page_id: str
) -> tuple[str, dict[str, Any] | None, Path]:
    """Find a bundle slug for this page.

    Returns ``(slug, existing_fm_or_None, index_path)``. A match by
    ``source_notion_id`` returns that bundle's front matter for the caller's
    idempotency check; a free slug returns ``None``.
    """
    base = date.isoformat()
    for slug in _slug_candidates(base):
        index = posts_dir / slug / "index.md"
        if not index.exists():
            return slug, None, index
        fm = _read_front_matter(index)
        if fm and fm.get("source_notion_id") == page_id:
            return slug, fm, index
    raise hugo.HugoError(f"no free slug near {base} (tried up to -{_MAX_SLUG_SUFFIX})")


def _slug_candidates(base: str):
    yield base
    for i in range(2, _MAX_SLUG_SUFFIX + 1):
        yield f"{base}-{i}"


def _read_front_matter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return hugo.parse_front_matter(text)


def _is_up_to_date(existing_fm: dict, notion_last_edited: str) -> bool:
    """Return True when the existing bundle's ``lastmod`` is ≥ Notion's value.

    Missing either timestamp ⇒ treat as stale (be safe, overwrite).
    """
    existing = existing_fm.get("lastmod")
    if not existing or not notion_last_edited:
        return False
    try:
        existing_dt = _parse_iso(str(existing))
        notion_dt = _parse_iso(notion_last_edited)
    except ValueError:
        return False
    return existing_dt >= notion_dt


def _parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# --- front matter build ------------------------------------------------------


def _build_front_matter(meta: _PageMeta, *, slug: str, now: datetime) -> dict[str, Any]:
    lastmod = _notion_time_to_kst_iso(meta.last_edited_time) or now.isoformat()
    fm: dict[str, Any] = {
        "title": meta.title,
        "date": meta.date_iso,
        "lastmod": lastmod,
        "draft": True,
        "slug": slug,
        "categories": [meta.category] if meta.category else [hugo.DEFAULT_CATEGORY],
    }
    if meta.tags:
        fm["tags"] = meta.tags
    if meta.summary:
        fm["description"] = meta.summary
    fm["source_notion_id"] = meta.page_id
    return fm


def _notion_time_to_kst_iso(raw: str) -> str:
    if not raw:
        return ""
    try:
        return _parse_iso(raw).astimezone(hugo.KST).isoformat()
    except ValueError:
        return ""
