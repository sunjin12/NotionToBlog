"""Per-block-type renderer tests.

The renderer is a pure function — children are supplied via an injectable
``fetch_children`` callable, images via an :class:`ImageCollector`. No network,
no filesystem.
"""

from __future__ import annotations

from typing import Any

import pytest

from dayblog.notion.images import ImageCollector
from dayblog.notion.render import (
    SUPPORTED_BLOCK_TYPES,
    RenderContext,
    render_blocks,
    render_rich_text,
)


# --- factories ----------------------------------------------------------------


def _rt(text: str, **ann: bool) -> list[dict]:
    return [{"plain_text": text, "annotations": ann or {}, "href": None}]


def _block(type_: str, body: dict | None = None, *, id: str = "B", has_children: bool = False) -> dict:
    return {"id": id, "type": type_, type_: body or {}, "has_children": has_children}


def _ctx(
    *,
    children: dict[str, list[dict]] | None = None,
    page_id: str = "page-xyz",
) -> RenderContext:
    children = children or {}
    return RenderContext(
        page_id=page_id,
        fetch_children=lambda bid: children.get(bid, []),
        collector=ImageCollector(page_id=page_id),
    )


def _render_one(block: dict, **ctx_kwargs: Any) -> tuple[str, RenderContext]:
    ctx = _ctx(**ctx_kwargs)
    return render_blocks([block], ctx), ctx


# --- rich text ----------------------------------------------------------------


def test_rich_text_plain_concatenation():
    spans = [
        {"plain_text": "Hello ", "annotations": {}, "href": None},
        {"plain_text": "world", "annotations": {}, "href": None},
    ]
    assert render_rich_text(spans) == "Hello world"


def test_rich_text_annotations_compose_in_order():
    # bold + italic + code + link together
    spans = [
        {
            "plain_text": "x",
            "annotations": {"bold": True, "italic": True, "code": True},
            "href": "https://example.com",
        }
    ]
    # code innermost, then italic, then bold, then link outer
    assert render_rich_text(spans) == "[***`x`***](https://example.com)"


def test_rich_text_underline_uses_html_tag():
    spans = [{"plain_text": "x", "annotations": {"underline": True}, "href": None}]
    assert render_rich_text(spans) == "<u>x</u>"


def test_rich_text_strikethrough_and_link():
    spans = [
        {
            "plain_text": "deleted",
            "annotations": {"strikethrough": True},
            "href": "https://x",
        }
    ]
    assert render_rich_text(spans) == "[~~deleted~~](https://x)"


# --- single-block renderers ---------------------------------------------------


def test_paragraph_appends_blank_line():
    out, _ = _render_one(_block("paragraph", {"rich_text": _rt("Hello")}))
    assert out == "Hello\n\n"


def test_paragraph_empty_renders_blank_line_only():
    out, _ = _render_one(_block("paragraph", {"rich_text": []}))
    assert out == "\n"


@pytest.mark.parametrize("level,prefix", [(1, "#"), (2, "##"), (3, "###")])
def test_heading_levels(level: int, prefix: str):
    out, _ = _render_one(_block(f"heading_{level}", {"rich_text": _rt("T")}))
    assert out == f"{prefix} T\n\n"


def test_bulleted_list_without_children():
    out, _ = _render_one(_block("bulleted_list_item", {"rich_text": _rt("item")}))
    assert out == "- item\n"


def test_bulleted_list_with_nested_children_indents_by_two_spaces():
    parent = _block("bulleted_list_item", {"rich_text": _rt("parent")}, id="P", has_children=True)
    child = _block("bulleted_list_item", {"rich_text": _rt("child")})
    out, _ = _render_one(parent, children={"P": [child]})
    assert out == "- parent\n  - child\n"


def test_numbered_list_uses_three_space_indent():
    parent = _block("numbered_list_item", {"rich_text": _rt("one")}, id="P", has_children=True)
    child = _block("numbered_list_item", {"rich_text": _rt("one-a")})
    out, _ = _render_one(parent, children={"P": [child]})
    assert out == "1. one\n   1. one-a\n"


def test_to_do_respects_checked_state():
    unchecked = _block("to_do", {"rich_text": _rt("todo"), "checked": False})
    checked = _block("to_do", {"rich_text": _rt("done"), "checked": True})
    ctx = _ctx()
    out = render_blocks([unchecked, checked], ctx)
    assert out == "- [ ] todo\n- [x] done\n"


def test_toggle_wraps_children_in_details_tag():
    parent = _block("toggle", {"rich_text": _rt("click me")}, id="T", has_children=True)
    child = _block("paragraph", {"rich_text": _rt("hidden")})
    out, _ = _render_one(parent, children={"T": [child]})
    assert out == "<details><summary>click me</summary>\n\nhidden\n\n</details>\n\n"


def test_code_block_uses_language_fence():
    body = {"rich_text": _rt("print('hi')"), "language": "python"}
    out, _ = _render_one(_block("code", body))
    assert out == "```python\nprint('hi')\n```\n\n"


def test_code_block_plain_text_language_strips_fence():
    body = {"rich_text": _rt("raw"), "language": "plain text"}
    out, _ = _render_one(_block("code", body))
    assert out == "```\nraw\n```\n\n"


def test_quote_prefixes_each_line():
    body = {"rich_text": _rt("line1\nline2")}
    out, _ = _render_one(_block("quote", body))
    assert out == "> line1\n> line2\n\n"


def test_callout_emits_icon_as_bold_prefix():
    body = {
        "rich_text": _rt("Heads up"),
        "icon": {"type": "emoji", "emoji": "💡"},
    }
    out, _ = _render_one(_block("callout", body))
    assert out == "> **💡** Heads up\n\n"


def test_callout_without_emoji_icon_is_still_quote():
    body = {"rich_text": _rt("just text"), "icon": None}
    out, _ = _render_one(_block("callout", body))
    assert out == "> just text\n\n"


def test_divider_emits_horizontal_rule():
    out, _ = _render_one(_block("divider"))
    assert out == "---\n\n"


def test_image_external_registers_and_returns_hashed_href():
    body = {
        "type": "external",
        "external": {"url": "https://example.com/photo.png"},
        "caption": _rt("a cat"),
    }
    out, ctx = _render_one(_block("image", body, id="IMG"))
    assert ctx.collector.refs and ctx.collector.refs[0].url == "https://example.com/photo.png"
    href = ctx.collector.refs[0].markdown_href
    assert out == f"![a cat]({href})\n\n"


def test_image_file_type_extracts_signed_url():
    body = {
        "type": "file",
        "file": {"url": "https://s3/signed?X=1", "expiry_time": "..."},
        "caption": [],
    }
    out, ctx = _render_one(_block("image", body, id="IMG"))
    assert ctx.collector.refs[0].url == "https://s3/signed?X=1"
    assert out.startswith("![](")


def test_image_without_url_warns_and_emits_nothing():
    body = {"type": "external", "external": {"url": ""}, "caption": []}
    out, ctx = _render_one(_block("image", body))
    assert out == ""
    assert any("without URL" in w for w in ctx.warnings)


def test_equation_uses_block_math_delimiters():
    out, _ = _render_one(_block("equation", {"expression": "E = mc^2"}))
    assert out == "$$E = mc^2$$\n\n"


def test_bookmark_becomes_self_linking_anchor():
    out, _ = _render_one(_block("bookmark", {"url": "https://ex.com"}))
    assert out == "[https://ex.com](https://ex.com)\n\n"


def test_link_preview_uses_bookmark_renderer():
    out, _ = _render_one(_block("link_preview", {"url": "https://ex.com/p/1"}))
    assert out == "[https://ex.com/p/1](https://ex.com/p/1)\n\n"


def test_unsupported_block_type_logs_warning_and_emits_nothing():
    out, ctx = _render_one(_block("table", {"rows": []}))
    assert out == ""
    assert any("unsupported block type" in w and "table" in w for w in ctx.warnings)


# --- meta ---------------------------------------------------------------------


def test_supported_block_types_covers_domain_notes_table():
    # domain-notes §5 enumerates 15 supported block types. link_preview reuses
    # the bookmark renderer, so the dispatch table has 16 entries total.
    expected = {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "code",
        "quote",
        "callout",
        "divider",
        "image",
        "equation",
        "bookmark",
        "link_preview",
    }
    assert SUPPORTED_BLOCK_TYPES == expected
