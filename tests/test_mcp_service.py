"""Unit tests for ``dayblog_mcp.service`` — pure NotionClient + renderer glue.

All tests use a FakeClient stub; no FastMCP runtime, no Notion network.
"""

from __future__ import annotations

from typing import Any

from dayblog_mcp.service import (
    get_page,
    list_pages_for_date,
    render_page_markdown,
    today_kst_iso,
)

# --- fakes --------------------------------------------------------------------


class FakeClient:
    def __init__(
        self,
        *,
        pages: list[dict] | None = None,
        page_data: dict[str, dict] | None = None,
        children: dict[str, list[dict]] | None = None,
    ) -> None:
        self._pages = pages or []
        self._page_data = page_data or {}
        self._children = children or {}
        self.calls: list[tuple[str, Any, dict]] = []

    def query_database(
        self,
        database_id: str,
        *,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
    ) -> list[dict]:
        self.calls.append(("query", database_id, {"filter": filter, "sorts": sorts}))
        return self._pages

    def retrieve_page(self, page_id: str) -> dict:
        self.calls.append(("retrieve", page_id, {}))
        return self._page_data.get(page_id, {"id": page_id})

    def list_children(self, block_id: str) -> list[dict]:
        self.calls.append(("children", block_id, {}))
        return self._children.get(block_id, [])


def _page(
    id_: str,
    *,
    title: str,
    date: str,
    status: str = "Ready",
    last_edited: str = "2026-04-24T12:00:00.000Z",
) -> dict:
    return {
        "id": id_,
        "last_edited_time": last_edited,
        "properties": {
            "Title": {"type": "title", "title": [{"plain_text": title}]},
            "Date": {"type": "date", "date": {"start": date}},
            "Status": {"type": "select", "select": {"name": status}},
        },
    }


def _rt(text: str) -> list[dict]:
    return [{"plain_text": text, "annotations": {}, "href": None}]


def _block(
    type_: str,
    body: dict | None = None,
    *,
    id_: str = "B",
    has_children: bool = False,
) -> dict:
    return {"id": id_, "type": type_, type_: body or {}, "has_children": has_children}


def _with_marker(blocks: list[dict]) -> list[dict]:
    # Domain-notes §9: render_page_markdown only emits Markdown for blocks
    # after the top-level Heading 1 "블로그". Tests that supply body blocks
    # prepend the marker via this helper.
    marker = _block("heading_1", {"rich_text": _rt("블로그")}, id_="MARKER")
    return [marker, *blocks]


# --- today_kst_iso ------------------------------------------------------------


def test_today_kst_iso_returns_iso_date_shape():
    out = today_kst_iso()
    assert len(out) == 10 and out[4] == "-" and out[7] == "-"
    year, month, day = out.split("-")
    assert year.isdigit() and month.isdigit() and day.isdigit()


# --- list_pages_for_date ------------------------------------------------------


def test_list_pages_builds_filter_for_ready_status_and_date():
    client = FakeClient(pages=[_page("p1", title="월요일 일기", date="2026-04-24")])
    list_pages_for_date(client, "db-1", date="2026-04-24")
    kind, db_id, kw = client.calls[0]
    assert kind == "query"
    assert db_id == "db-1"
    conds = kw["filter"]["and"]
    assert {"property": "Status", "select": {"equals": "Ready"}} in conds
    assert {"property": "Date", "date": {"equals": "2026-04-24"}} in conds
    assert kw["sorts"] == [{"property": "Date", "direction": "ascending"}]


def test_list_pages_summarizes_each_page():
    pages = [
        _page("p1", title="A", date="2026-04-24"),
        _page(
            "p2",
            title="B",
            date="2026-04-24",
            last_edited="2026-04-24T13:00:00.000Z",
        ),
    ]
    out = list_pages_for_date(FakeClient(pages=pages), "db-1", date="2026-04-24")
    assert out == [
        {
            "id": "p1",
            "title": "A",
            "date": "2026-04-24",
            "status": "Ready",
            "last_edited_time": "2026-04-24T12:00:00.000Z",
        },
        {
            "id": "p2",
            "title": "B",
            "date": "2026-04-24",
            "status": "Ready",
            "last_edited_time": "2026-04-24T13:00:00.000Z",
        },
    ]


def test_list_pages_tolerates_missing_optional_properties():
    page = {
        "id": "p1",
        "last_edited_time": "",
        "properties": {"Title": {"type": "title", "title": []}},
    }
    out = list_pages_for_date(FakeClient(pages=[page]), "db-1", date="2026-04-24")
    assert out == [
        {
            "id": "p1",
            "title": "",
            "date": "",
            "status": "",
            "last_edited_time": "",
        }
    ]


def test_list_pages_accepts_name_as_title_fallback():
    # Some Notion DBs keep the default title property named "Name".
    page = {
        "id": "p1",
        "last_edited_time": "",
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "fallback"}]}},
    }
    out = list_pages_for_date(FakeClient(pages=[page]), "db-1", date="2026-04-24")
    assert out[0]["title"] == "fallback"


# --- get_page -----------------------------------------------------------------


def test_get_page_returns_page_metadata_and_top_level_blocks():
    page = {"id": "p1", "properties": {}}
    blocks = [_block("paragraph", {"rich_text": _rt("hello")}, id_="b1")]
    client = FakeClient(page_data={"p1": page}, children={"p1": blocks})
    out = get_page(client, "p1")
    assert out == {"page": page, "blocks": blocks}


def test_get_page_does_not_recurse_into_children():
    blocks = [_block("paragraph", {"rich_text": _rt("x")}, id_="b1", has_children=True)]
    client = FakeClient(children={"p1": blocks, "b1": [_block("paragraph")]})
    get_page(client, "p1")
    # "children" was fetched only for page_id, not for b1
    children_calls = [c for c in client.calls if c[0] == "children"]
    assert [c[1] for c in children_calls] == ["p1"]


# --- render_page_markdown -----------------------------------------------------


def test_render_markdown_renders_top_level_blocks():
    blocks = [
        _block("heading_1", {"rich_text": _rt("제목")}),
        _block("paragraph", {"rich_text": _rt("본문")}),
    ]
    out = render_page_markdown(FakeClient(children={"p1": _with_marker(blocks)}), "p1")
    assert out["markdown"] == "# 제목\n\n본문\n\n"
    assert out["images"] == []
    assert out["warnings"] == []


def test_render_markdown_recurses_into_nested_children():
    parent = _block("bulleted_list_item", {"rich_text": _rt("부모")}, id_="P", has_children=True)
    child = _block("bulleted_list_item", {"rich_text": _rt("자식")})
    client = FakeClient(children={"p1": _with_marker([parent]), "P": [child]})
    out = render_page_markdown(client, "p1")
    assert out["markdown"] == "- 부모\n  - 자식\n"


def test_render_markdown_builds_image_manifest():
    body = {
        "type": "external",
        "external": {"url": "https://example.com/cat.png"},
        "caption": _rt("고양이"),
    }
    client = FakeClient(children={"p1": _with_marker([_block("image", body, id_="IMG")])})
    out = render_page_markdown(client, "p1")
    assert len(out["images"]) == 1
    img = out["images"][0]
    assert img["url"] == "https://example.com/cat.png"
    assert img["block_id"] == "IMG"
    assert img["caption"] == "고양이"
    assert img["filename"].startswith("img-") and img["filename"].endswith(".png")


def test_render_markdown_surfaces_renderer_warnings():
    client = FakeClient(children={"p1": _with_marker([_block("table", id_="T")])})
    out = render_page_markdown(client, "p1")
    assert out["markdown"] == ""
    assert any("unsupported block type" in w and "table" in w for w in out["warnings"])


# --- 블로그 marker (domain-notes §9) ------------------------------------------


def test_render_markdown_warns_when_marker_missing():
    # No "블로그" Heading 1 → empty markdown + a clear warning the MCP UI can show.
    blocks = [_block("paragraph", {"rich_text": _rt("personal diary")})]
    client = FakeClient(children={"p1": blocks})
    out = render_page_markdown(client, "p1")
    assert out["markdown"] == ""
    assert any("블로그" in w for w in out["warnings"])


def test_render_markdown_skips_blocks_before_marker():
    diary = _block("paragraph", {"rich_text": _rt("PRIVATE")}, id_="D")
    marker = _block("heading_1", {"rich_text": _rt("블로그")}, id_="M")
    public = _block("paragraph", {"rich_text": _rt("PUBLIC")}, id_="P")
    client = FakeClient(children={"p1": [diary, marker, public]})
    out = render_page_markdown(client, "p1")
    assert "PRIVATE" not in out["markdown"]
    assert "PUBLIC" in out["markdown"]
