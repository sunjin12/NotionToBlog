"""FastMCP server exposing the Notion → Markdown pipeline as MCP tools.

Three tools are registered:

- ``notion_list_pages(date?)`` — Notion DB pages with ``Status == Ready`` on
  the given ISO date (default: today in KST).
- ``notion_get_page(page_id)`` — raw page metadata + top-level blocks.
- ``notion_render_markdown(page_id)`` — Markdown + image manifest + warnings.

The ``NotionClient`` is built lazily on first use (keeps import cheap and lets
tests inject a fake via :func:`_set_client`). Secrets are read from the repo-root
``.env`` or process env: ``NOTION_TOKEN`` and ``NOTION_DATABASE_ID``.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from dayblog.notion.client import NotionClient

from . import service

mcp = FastMCP("dayblog")

_client: NotionClient | None = None


def _set_client(client: NotionClient | None) -> None:
    """Test hook — lets tests inject a fake client without touching env or HTTP."""
    global _client
    _client = client


def _get_client() -> NotionClient:
    global _client
    if _client is None:
        load_dotenv(override=False)
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            raise RuntimeError(
                "NOTION_TOKEN missing — add it to repo-root .env or the process env"
            )
        _client = NotionClient(token=token)
    return _client


def _get_database_id() -> str:
    load_dotenv(override=False)
    db = os.environ.get("NOTION_DATABASE_ID")
    if not db:
        raise RuntimeError(
            "NOTION_DATABASE_ID missing — add it to repo-root .env or the process env"
        )
    return db


@mcp.tool
def notion_list_pages(date: str | None = None) -> list[dict]:
    """List Notion diary pages with ``Status == Ready`` on the given date.

    Args:
        date: ISO date ``YYYY-MM-DD``. Defaults to today in KST (+09:00).

    Returns:
        List of summary dicts: ``id``, ``title``, ``date``, ``status``,
        ``last_edited_time``.
    """
    effective = date or service.today_kst_iso()
    return service.list_pages_for_date(_get_client(), _get_database_id(), date=effective)


@mcp.tool
def notion_get_page(page_id: str) -> dict:
    """Fetch raw Notion page metadata + top-level blocks (no rendering).

    Use this to inspect property shapes before wiring new mappings. Nested
    children are **not** fetched — top-level blocks only.
    """
    return service.get_page(_get_client(), page_id)


@mcp.tool
def notion_render_markdown(page_id: str) -> dict:
    """Render a Notion page to Hugo-ready Markdown plus an image manifest.

    Returns ``{"markdown": str, "images": [{block_id, url, filename, caption}],
    "warnings": [str]}``. Image bytes are not downloaded here — Phase 3 does
    that during publish.
    """
    return service.render_page_markdown(_get_client(), page_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
