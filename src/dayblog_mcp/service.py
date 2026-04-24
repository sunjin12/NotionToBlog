"""Pure service layer wrapping :class:`NotionClient` + renderer.

The FastMCP ``server.py`` thin-wraps these functions. Keeping the business
logic here — free of any FastMCP import — is what lets the bulk of the MCP
surface be tested with a fake client, without spinning up a runtime or
touching the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from dayblog.notion.images import ImageCollector
from dayblog.notion.render import RenderContext, render_blocks

KST = timezone(timedelta(hours=9))


class _ClientLike(Protocol):
    def query_database(
        self,
        database_id: str,
        *,
        filter: dict | None = ...,
        sorts: list[dict] | None = ...,
    ) -> list[dict]: ...

    def retrieve_page(self, page_id: str) -> dict: ...

    def list_children(self, block_id: str) -> list[dict]: ...


def today_kst_iso() -> str:
    """Return today's date in KST as ``YYYY-MM-DD`` (matches Notion ``date.equals``)."""
    return datetime.now(KST).date().isoformat()


def list_pages_for_date(
    client: _ClientLike,
    database_id: str,
    *,
    date: str,
) -> list[dict]:
    """Query the Notion DB for ``Status == Ready`` pages on ``date``.

    Each result is a compact summary (id, title, date, status, last_edited_time) —
    enough for the Claude UI to render a picker without a second round-trip.
    """
    filter_: dict[str, Any] = {
        "and": [
            {"property": "Status", "select": {"equals": "Ready"}},
            {"property": "Date", "date": {"equals": date}},
        ]
    }
    sorts = [{"property": "Date", "direction": "ascending"}]
    pages = client.query_database(database_id, filter=filter_, sorts=sorts)
    return [_summarize_page(p) for p in pages]


def get_page(client: _ClientLike, page_id: str) -> dict:
    """Fetch page metadata + top-level blocks. No recursion, no rendering — raw."""
    page = client.retrieve_page(page_id)
    blocks = client.list_children(page_id)
    return {"page": page, "blocks": blocks}


def render_page_markdown(client: _ClientLike, page_id: str) -> dict:
    """Render a Notion page as Markdown plus image refs and renderer warnings.

    Image files are **not** downloaded here — Phase 3 will do that during the
    publish step. The returned ``images`` list is the manifest the downloader
    consumes.
    """
    top = client.list_children(page_id)
    collector = ImageCollector(page_id=page_id)
    ctx = RenderContext(
        page_id=page_id,
        fetch_children=client.list_children,
        collector=collector,
    )
    markdown = render_blocks(top, ctx)
    return {
        "markdown": markdown,
        "images": [
            {
                "block_id": ref.block_id,
                "url": ref.url,
                "filename": ref.filename,
                "caption": ref.caption,
            }
            for ref in collector.refs
        ],
        "warnings": list(ctx.warnings),
    }


# --- internals ----------------------------------------------------------------


def _summarize_page(page: dict) -> dict:
    props = page.get("properties") or {}
    return {
        "id": page.get("id", ""),
        "title": _extract_title(props.get("Title") or props.get("Name") or {}),
        "date": _extract_date(props.get("Date") or {}),
        "status": _extract_select(props.get("Status") or {}),
        "last_edited_time": page.get("last_edited_time", ""),
    }


def _extract_title(prop: dict) -> str:
    if prop.get("type") != "title":
        return ""
    return "".join(span.get("plain_text", "") for span in prop.get("title") or [])


def _extract_date(prop: dict) -> str:
    if prop.get("type") != "date":
        return ""
    return (prop.get("date") or {}).get("start", "")


def _extract_select(prop: dict) -> str:
    if prop.get("type") != "select":
        return ""
    return (prop.get("select") or {}).get("name", "")
