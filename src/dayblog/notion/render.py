"""Notion block tree → Markdown renderer.

Dispatches per Notion block type (domain-notes §5). 15 supported types cover a
personal diary fully; unsupported types (``table``, ``video``, embeds, …) emit
a warning and render nothing — we log rather than fail so a single unexpected
block doesn't kill the whole publish flow.

The renderer itself is a pure function: children are fetched via the
``fetch_children`` callable and images are registered via ``collector``. No
network I/O or filesystem access happens inside this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .images import ImageCollector

BLOG_SECTION_MARKER = "블로그"


@dataclass
class RenderContext:
    """Inputs the renderer needs that aren't in the block dict itself."""

    page_id: str
    fetch_children: Callable[[str], list[dict]]
    collector: ImageCollector
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


# --- public API ---------------------------------------------------------------


def render_blocks(blocks: list[dict], ctx: RenderContext) -> str:
    """Render a list of sibling blocks at the top level (no indent, no quote)."""
    return "".join(_render_block(b, ctx) for b in blocks)


def render_rich_text(rich_text: list[dict]) -> str:
    """Notion ``rich_text`` array → inline Markdown string.

    Annotation order: ``code`` wraps innermost, then ``strikethrough``,
    ``italic``, ``bold``, ``underline`` (as ``<u>`` HTML), then link — so the
    resulting Markdown reads e.g. ``[**`snippet`**](url)``.
    """
    parts: list[str] = []
    for span in rich_text:
        text = span.get("plain_text", "")
        if not text:
            continue
        ann = span.get("annotations") or {}
        if ann.get("code"):
            text = f"`{text}`"
        if ann.get("strikethrough"):
            text = f"~~{text}~~"
        if ann.get("italic"):
            text = f"*{text}*"
        if ann.get("bold"):
            text = f"**{text}**"
        if ann.get("underline"):
            text = f"<u>{text}</u>"
        href = span.get("href")
        if href:
            text = f"[{text}]({href})"
        parts.append(text)
    return "".join(parts)


# --- dispatch -----------------------------------------------------------------


def _render_block(block: dict, ctx: RenderContext) -> str:
    btype = block.get("type")
    renderer = _RENDERERS.get(btype)
    if renderer is None:
        ctx.warn(f"unsupported block type: {btype} (id={block.get('id')})")
        return ""
    return renderer(block, ctx)


def _body(block: dict) -> dict:
    return block.get(block["type"]) or {}


def _rt(block: dict) -> str:
    return render_rich_text(_body(block).get("rich_text") or [])


def _paragraph(block: dict, ctx: RenderContext) -> str:
    text = _rt(block)
    return f"{text}\n\n" if text else "\n"


def _heading(level: int) -> Callable[[dict, RenderContext], str]:
    hashes = "#" * level

    def render(block: dict, ctx: RenderContext) -> str:
        return f"{hashes} {_rt(block)}\n\n"

    return render


def _bulleted_list_item(block: dict, ctx: RenderContext) -> str:
    return _render_list_item(block, ctx, marker="-", child_indent="  ")


def _numbered_list_item(block: dict, ctx: RenderContext) -> str:
    return _render_list_item(block, ctx, marker="1.", child_indent="   ")


def _render_list_item(block: dict, ctx: RenderContext, *, marker: str, child_indent: str) -> str:
    line = f"{marker} {_rt(block)}\n"
    if block.get("has_children"):
        children = ctx.fetch_children(block["id"])
        child_md = render_blocks(children, ctx)
        line += _indent(child_md, child_indent)
    return line


def _to_do(block: dict, ctx: RenderContext) -> str:
    body = _body(block)
    checked = "x" if body.get("checked") else " "
    line = f"- [{checked}] {render_rich_text(body.get('rich_text') or [])}\n"
    if block.get("has_children"):
        children = ctx.fetch_children(block["id"])
        line += _indent(render_blocks(children, ctx), "  ")
    return line


def _toggle(block: dict, ctx: RenderContext) -> str:
    summary = _rt(block)
    inner = ""
    if block.get("has_children"):
        inner = render_blocks(ctx.fetch_children(block["id"]), ctx)
    inner = inner.rstrip()
    # Hugo goldmark unsafe=true is required (domain-notes §1) for raw HTML.
    return f"<details><summary>{summary}</summary>\n\n{inner}\n\n</details>\n\n"


def _code(block: dict, ctx: RenderContext) -> str:
    body = _body(block)
    text = "".join(span.get("plain_text", "") for span in body.get("rich_text") or [])
    lang = body.get("language") or ""
    if lang in ("plain text", "plaintext"):
        lang = ""
    fence = f"```{lang}".rstrip()
    return f"{fence}\n{text}\n```\n\n"


def _quote(block: dict, ctx: RenderContext) -> str:
    text = _rt(block)
    lines = text.split("\n") if text else [""]
    out = "".join(f"> {line}\n" for line in lines)
    if block.get("has_children"):
        inner = render_blocks(ctx.fetch_children(block["id"]), ctx).rstrip()
        if inner:
            out += "".join(f"> {line}\n" for line in inner.split("\n"))
    return out + "\n"


def _callout(block: dict, ctx: RenderContext) -> str:
    body = _body(block)
    icon = body.get("icon") or {}
    prefix = ""
    if icon.get("type") == "emoji" and icon.get("emoji"):
        prefix = f"**{icon['emoji']}** "
    text = render_rich_text(body.get("rich_text") or [])
    out = f"> {prefix}{text}\n"
    if block.get("has_children"):
        inner = render_blocks(ctx.fetch_children(block["id"]), ctx).rstrip()
        if inner:
            out += "".join(f"> {line}\n" for line in inner.split("\n"))
    return out + "\n"


def _divider(block: dict, ctx: RenderContext) -> str:
    return "---\n\n"


def _image(block: dict, ctx: RenderContext) -> str:
    body = _body(block)
    url = _image_url(body)
    if not url:
        ctx.warn(f"image block without URL (id={block.get('id')})")
        return ""
    caption = render_rich_text(body.get("caption") or [])
    ref = ctx.collector.register(block_id=block["id"], url=url, caption=caption)
    alt = caption or ""
    return f"![{alt}]({ref.markdown_href})\n\n"


def _image_url(body: dict) -> str:
    kind = body.get("type")
    if kind == "external":
        return (body.get("external") or {}).get("url", "")
    if kind == "file":
        return (body.get("file") or {}).get("url", "")
    return ""


def _equation(block: dict, ctx: RenderContext) -> str:
    expr = _body(block).get("expression", "")
    return f"$${expr}$$\n\n"


def _bookmark_like(block: dict, ctx: RenderContext) -> str:
    url = _body(block).get("url", "")
    if not url:
        return ""
    return f"[{url}]({url})\n\n"


# --- helpers ------------------------------------------------------------------


def _indent(text: str, prefix: str) -> str:
    if not text:
        return ""
    return "".join(
        (prefix + line if line else line) + "\n"
        for line in text.rstrip("\n").split("\n")
    )


_RENDERERS: dict[str, Callable[[dict, RenderContext], str]] = {
    "paragraph": _paragraph,
    "heading_1": _heading(1),
    "heading_2": _heading(2),
    "heading_3": _heading(3),
    "bulleted_list_item": _bulleted_list_item,
    "numbered_list_item": _numbered_list_item,
    "to_do": _to_do,
    "toggle": _toggle,
    "code": _code,
    "quote": _quote,
    "callout": _callout,
    "divider": _divider,
    "image": _image,
    "equation": _equation,
    "bookmark": _bookmark_like,
    "link_preview": _bookmark_like,
}

SUPPORTED_BLOCK_TYPES: frozenset[str] = frozenset(_RENDERERS)


# --- marker-based section slicing --------------------------------------------


def slice_after_heading(
    blocks: list[dict],
    title: str,
    *,
    level: int = 1,
) -> tuple[list[dict], bool]:
    """Return ``(blocks_after_marker, marker_found)``.

    Walks ``blocks`` top-level (no recursion into children) looking for the
    first ``heading_{level}`` whose rich_text stripped equals ``title.strip()``.
    On match the function returns every sibling after that heading (the
    heading itself is not included) with ``marker_found=True``. On no match
    it returns ``([], False)`` so callers decide whether to skip, warn, or
    fall back to the full list — the tuple keeps the decision close to the
    publish flow (see domain-notes §9).
    """
    needle = title.strip()
    target_type = f"heading_{level}"
    for i, block in enumerate(blocks):
        if block.get("type") != target_type:
            continue
        body = block.get(target_type) or {}
        text = render_rich_text(body.get("rich_text") or []).strip()
        if text == needle:
            return list(blocks[i + 1:]), True
    return [], False
