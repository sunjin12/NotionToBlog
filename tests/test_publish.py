"""Tests for :mod:`dayblog.publish` — Notion page → Hugo bundle orchestration.

All tests use a FakeClient + dict-backed ``http_get``; no network, no Notion.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from dayblog import hugo
from dayblog.publish import PublishResult, publish_page

KST = hugo.KST


# --- fakes --------------------------------------------------------------------


class FakeClient:
    def __init__(
        self,
        *,
        pages: dict[str, dict],
        children: dict[str, list[dict]] | None = None,
    ) -> None:
        self._pages = pages
        self._children = children or {}
        self.calls: list[tuple[str, str]] = []

    def retrieve_page(self, page_id: str) -> dict:
        self.calls.append(("retrieve", page_id))
        return self._pages[page_id]

    def list_children(self, block_id: str) -> list[dict]:
        self.calls.append(("children", block_id))
        return self._children.get(block_id, [])


def _notion_page(
    page_id: str,
    *,
    date: str,
    title: str = "제목",
    last_edited: str = "2026-04-24T12:00:00.000Z",
    tags: list[str] | None = None,
    category: str | None = None,
    summary: str = "",
) -> dict:
    props: dict = {
        "Title": {"type": "title", "title": [{"plain_text": title}]},
        "Date": {"type": "date", "date": {"start": date}},
    }
    if tags:
        props["Tags"] = {
            "type": "multi_select",
            "multi_select": [{"name": t} for t in tags],
        }
    if category:
        props["Category"] = {"type": "select", "select": {"name": category}}
    if summary:
        props["Summary"] = {
            "type": "rich_text",
            "rich_text": [{"plain_text": summary}],
        }
    return {"id": page_id, "last_edited_time": last_edited, "properties": props}


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
    # Domain-notes §9: publish_page only renders blocks after the top-level
    # Heading 1 "블로그". Tests that supply a block list for the *body* prepend
    # the marker through this helper so the publish flow sees both the
    # gate and the body.
    marker = _block("heading_1", {"rich_text": _rt("블로그")}, id_="MARKER")
    return [marker, *blocks]


def _read_fm(path: Path) -> dict:
    fm = hugo.parse_front_matter(path.read_text(encoding="utf-8"))
    assert fm is not None
    return fm


# --- create path --------------------------------------------------------------


def test_publish_creates_new_bundle_with_required_front_matter(tmp_path: Path):
    page = _notion_page("page-1", date="2026-04-24", title="월요일")
    blocks = [_block("paragraph", {"rich_text": _rt("hello")})]
    client = FakeClient(pages={"page-1": page}, children={"page-1": _with_marker(blocks)})

    result = publish_page(
        client=client,
        page_id="page-1",
        site_root=tmp_path,
        now=datetime(2026, 4, 24, 10, 30, 0, tzinfo=KST),
    )

    assert result.status == "created"
    assert result.path == tmp_path / "content" / "posts" / "2026-04-24" / "index.md"
    fm = _read_fm(result.path)
    assert fm["title"] == "월요일"
    assert fm["slug"] == "2026-04-24"
    assert fm["draft"] is True
    assert fm["source_notion_id"] == "page-1"
    assert fm["categories"] == ["일지"]
    assert result.path.read_text(encoding="utf-8").endswith("hello\n")


def test_publish_includes_tags_category_and_summary(tmp_path: Path):
    page = _notion_page(
        "page-1",
        date="2026-04-24",
        title="T",
        tags=["일기", "회고"],
        category="개발",
        summary="짧은 요약",
    )
    client = FakeClient(pages={"page-1": page}, children={"page-1": _with_marker([])})
    result = publish_page(client=client, page_id="page-1", site_root=tmp_path)
    fm = _read_fm(result.path)
    assert fm["tags"] == ["일기", "회고"]
    assert fm["categories"] == ["개발"]
    assert fm["description"] == "짧은 요약"


def test_publish_synthesizes_time_when_notion_date_is_date_only(tmp_path: Path):
    page = _notion_page("p", date="2026-04-24", title="X")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})
    result = publish_page(
        client=client,
        page_id="p",
        site_root=tmp_path,
        now=datetime(2026, 4, 24, 9, 0, 0, tzinfo=KST),
    )
    fm = _read_fm(result.path)
    assert fm["date"] == "2026-04-24T09:00:00+09:00"


def test_publish_keeps_notion_datetime_when_date_has_time(tmp_path: Path):
    page = _notion_page("p", date="2026-04-24T15:30:00+09:00", title="X")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})
    result = publish_page(client=client, page_id="p", site_root=tmp_path)
    fm = _read_fm(result.path)
    assert fm["date"] == "2026-04-24T15:30:00+09:00"


def test_publish_converts_lastmod_to_kst(tmp_path: Path):
    page = _notion_page("p", date="2026-04-24", last_edited="2026-04-24T03:00:00.000Z")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})
    result = publish_page(client=client, page_id="p", site_root=tmp_path)
    fm = _read_fm(result.path)
    # UTC 03:00 → KST 12:00
    assert "T12:00:00+09:00" in str(fm["lastmod"])


# --- idempotency --------------------------------------------------------------


def test_publish_skips_when_existing_lastmod_is_current(tmp_path: Path):
    page = _notion_page("p", date="2026-04-24", last_edited="2026-04-24T03:00:00.000Z")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})

    # First publish creates the bundle.
    first = publish_page(client=client, page_id="p", site_root=tmp_path)
    assert first.status == "created"

    # Rerun without any Notion change → skip.
    second = publish_page(client=client, page_id="p", site_root=tmp_path)
    assert second.status == "skipped"
    assert second.path == first.path


def test_publish_updates_when_notion_page_is_newer(tmp_path: Path):
    page = _notion_page("p", date="2026-04-24", last_edited="2026-04-24T03:00:00.000Z", title="old")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})
    publish_page(client=client, page_id="p", site_root=tmp_path)

    # Bump Notion lastmod and title.
    client._pages["p"] = _notion_page(
        "p", date="2026-04-24", last_edited="2026-04-25T09:00:00.000Z", title="new"
    )
    result = publish_page(client=client, page_id="p", site_root=tmp_path)
    assert result.status == "updated"
    assert _read_fm(result.path)["title"] == "new"


def test_publish_treats_missing_lastmod_as_stale(tmp_path: Path):
    # Hand-craft an existing bundle without lastmod — should be overwritten.
    posts = tmp_path / "content" / "posts" / "2026-04-24"
    posts.mkdir(parents=True)
    (posts / "index.md").write_text(
        "---\n"
        + yaml.safe_dump(
            {
                "title": "stale",
                "date": "2026-04-24T09:00:00+09:00",
                "draft": True,
                "slug": "2026-04-24",
                "source_notion_id": "p",
            },
            allow_unicode=True,
            sort_keys=False,
        )
        + "---\nold body\n",
        encoding="utf-8",
    )
    page = _notion_page("p", date="2026-04-24", last_edited="2026-04-24T10:00:00.000Z", title="fresh")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})
    result = publish_page(client=client, page_id="p", site_root=tmp_path)
    assert result.status == "updated"
    assert _read_fm(result.path)["title"] == "fresh"


# --- slug collisions ----------------------------------------------------------


def test_publish_picks_suffix_when_different_page_owns_base_slug(tmp_path: Path):
    # Pre-existing bundle at 2026-04-24 owned by page "other".
    posts = tmp_path / "content" / "posts" / "2026-04-24"
    posts.mkdir(parents=True)
    (posts / "index.md").write_text(
        "---\n"
        + yaml.safe_dump(
            {
                "title": "existing",
                "date": "2026-04-24T09:00:00+09:00",
                "draft": False,
                "slug": "2026-04-24",
                "source_notion_id": "other",
            },
            allow_unicode=True,
            sort_keys=False,
        )
        + "---\n",
        encoding="utf-8",
    )

    page = _notion_page("new", date="2026-04-24", title="mine")
    client = FakeClient(pages={"new": page}, children={"new": _with_marker([])})
    result = publish_page(client=client, page_id="new", site_root=tmp_path)
    assert result.status == "created"
    assert result.path.parent.name == "2026-04-24-2"
    fm = _read_fm(result.path)
    assert fm["slug"] == "2026-04-24-2"


def test_publish_reuses_numbered_slug_when_owner_matches(tmp_path: Path):
    # Base is owned by someone else; new page takes -2 on first run, should
    # reuse -2 (not hop to -3) on subsequent runs.
    posts_root = tmp_path / "content" / "posts"
    (posts_root / "2026-04-24").mkdir(parents=True)
    (posts_root / "2026-04-24" / "index.md").write_text(
        "---\n"
        + yaml.safe_dump(
            {
                "title": "taken",
                "date": "2026-04-24T09:00:00+09:00",
                "draft": False,
                "slug": "2026-04-24",
                "source_notion_id": "other",
            },
            allow_unicode=True,
            sort_keys=False,
        )
        + "---\n",
        encoding="utf-8",
    )
    page = _notion_page("mine", date="2026-04-24", last_edited="2026-04-24T01:00:00Z")
    client = FakeClient(pages={"mine": page}, children={"mine": _with_marker([])})
    first = publish_page(client=client, page_id="mine", site_root=tmp_path)
    assert first.path.parent.name == "2026-04-24-2"

    client._pages["mine"] = _notion_page(
        "mine", date="2026-04-24", last_edited="2026-04-24T02:00:00Z", title="updated"
    )
    second = publish_page(client=client, page_id="mine", site_root=tmp_path)
    assert second.status == "updated"
    assert second.path.parent.name == "2026-04-24-2"


# --- images -------------------------------------------------------------------


def test_publish_downloads_images_when_http_get_supplied(tmp_path: Path):
    image_body = {
        "type": "external",
        "external": {"url": "https://example.com/cat.png"},
        "caption": _rt("고양이"),
    }
    blocks = [_block("image", image_body, id_="IMG")]
    page = _notion_page("p", date="2026-04-24")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker(blocks)})

    store = {"https://example.com/cat.png": b"PNG_BYTES"}
    result = publish_page(
        client=client,
        page_id="p",
        site_root=tmp_path,
        http_get=store.__getitem__,
    )

    assert result.image_count == 1
    # Image dropped into the bundle dir alongside index.md
    bundle_files = sorted(p.name for p in result.path.parent.iterdir())
    assert "index.md" in bundle_files
    assert any(f.startswith("img-") and f.endswith(".png") for f in bundle_files)


def test_publish_without_http_get_skips_image_download(tmp_path: Path):
    image_body = {
        "type": "external",
        "external": {"url": "https://example.com/cat.png"},
        "caption": [],
    }
    blocks = [_block("image", image_body, id_="IMG")]
    page = _notion_page("p", date="2026-04-24")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker(blocks)})

    result = publish_page(client=client, page_id="p", site_root=tmp_path)
    assert result.image_count == 0
    # Only index.md was written.
    bundle_files = [p.name for p in result.path.parent.iterdir()]
    assert bundle_files == ["index.md"]


# --- errors + warnings -------------------------------------------------------


def test_publish_errors_when_date_property_is_missing(tmp_path: Path):
    page = {"id": "p", "last_edited_time": "", "properties": {}}
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([])})
    with pytest.raises(hugo.HugoError, match="Date"):
        publish_page(client=client, page_id="p", site_root=tmp_path)


def test_publish_surfaces_renderer_warnings(tmp_path: Path):
    page = _notion_page("p", date="2026-04-24")
    client = FakeClient(pages={"p": page}, children={"p": _with_marker([_block("table", id_="T")])})
    result = publish_page(client=client, page_id="p", site_root=tmp_path)
    assert any("unsupported block type" in w for w in result.warnings)


def test_publish_result_is_a_dataclass():
    # Contract check — slash command / CLI relies on these field names.
    assert {f for f in PublishResult.__dataclass_fields__} == {
        "path",
        "status",
        "image_count",
        "warnings",
    }


# --- 블로그 marker (domain-notes §9) ------------------------------------------


def test_publish_skips_page_without_blog_marker(tmp_path: Path):
    # No marker block in the children list — publish must refuse so the
    # personal diary above the (forgotten) marker can't leak.
    page = _notion_page("p", date="2026-04-24")
    blocks = [_block("paragraph", {"rich_text": _rt("personal diary content")})]
    client = FakeClient(pages={"p": page}, children={"p": blocks})

    result = publish_page(client=client, page_id="p", site_root=tmp_path)

    assert result.status == "skipped-no-marker"
    assert any("블로그" in w for w in result.warnings)
    # No bundle should have been created on disk.
    bundle_dir = tmp_path / "content" / "posts" / "2026-04-24"
    assert not bundle_dir.exists()


def test_publish_renders_only_blocks_after_blog_marker(tmp_path: Path):
    # Diary blocks above the marker must not appear in the rendered body.
    page = _notion_page("p", date="2026-04-24", title="T")
    diary = _block("paragraph", {"rich_text": _rt("PRIVATE DIARY")}, id_="D1")
    marker = _block("heading_1", {"rich_text": _rt("블로그")}, id_="M")
    public = _block("paragraph", {"rich_text": _rt("public body")}, id_="P1")
    client = FakeClient(pages={"p": page}, children={"p": [diary, marker, public]})

    result = publish_page(client=client, page_id="p", site_root=tmp_path)

    body = result.path.read_text(encoding="utf-8")
    assert "PRIVATE DIARY" not in body
    assert "public body" in body
