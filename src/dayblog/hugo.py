"""Hugo local tooling — page-bundle scaffolding + front-matter validation.

See docs/domain-notes.md §1-5 for the authoritative decisions this module implements.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

KST = timezone(timedelta(hours=9))

POSTS_SUBPATH = ("content", "posts")
DEFAULT_CATEGORY = "일지"
REQUIRED_FIELDS = ("title", "date", "draft", "slug")


class HugoError(Exception):
    """Raised for user-facing Hugo scaffolding errors."""


def new_post(
    *,
    site_root: Path,
    date: date_cls,
    title: str,
    tags: list[str] | None = None,
    categories: list[str] | None = None,
    description: str | None = None,
    source_notion_id: str | None = None,
    body: str = "",
    draft: bool = True,
    now: datetime | None = None,
) -> Path:
    """Create a Hugo page bundle at ``site_root/content/posts/<slug>/index.md``.

    Slug is the ISO date (``YYYY-MM-DD``). On collision with an existing bundle,
    appends ``-2``, ``-3``, … per domain-notes §4. Refuses to overwrite an
    existing ``index.md`` (defensive — the suffix loop normally avoids this).
    """
    if not title:
        raise HugoError("title must be non-empty")
    posts_dir = site_root.joinpath(*POSTS_SUBPATH)
    slug = _resolve_slug(posts_dir, date)
    bundle_dir = posts_dir / slug
    index = bundle_dir / "index.md"
    if index.exists():
        raise HugoError(f"refusing to overwrite existing file: {index}")

    now_dt = now or datetime.now(KST)
    # date component from `date`, time component from `now` (KST) — yields a stable
    # per-post timestamp without polluting the calendar date for same-day reruns.
    date_iso = datetime(
        date.year, date.month, date.day,
        now_dt.hour, now_dt.minute, now_dt.second,
        tzinfo=KST,
    ).isoformat()

    fm: dict[str, Any] = {
        "title": title,
        "date": date_iso,
        "draft": draft,
        "slug": slug,
        "categories": list(categories) if categories else [DEFAULT_CATEGORY],
    }
    if tags:
        fm["tags"] = list(tags)
    if description:
        fm["description"] = description
    if source_notion_id:
        fm["source_notion_id"] = source_notion_id

    bundle_dir.mkdir(parents=True, exist_ok=True)
    index.write_text(_render(fm, body), encoding="utf-8")
    return index


def validate_front_matter(path: Path) -> list[str]:
    """Return a list of validation errors. Empty list ⇒ valid.

    Rules (domain-notes §3):
    - ``title``, ``date``, ``draft``, ``slug`` are required.
    - ``slug`` must equal the bundle directory name (``index.md``) or the file
      stem (flat-format ``<slug>.md``).
    - ``tags`` / ``categories`` must be ``list[str]`` if present.
    - ``source_notion_id`` is optional; when present it must be a non-empty
      string. Phase 3 enforces its presence for Notion-sourced posts.
    """
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"{path}: file not found"]

    fm = _parse_front_matter(text)
    if fm is None:
        return [f"{path}: missing or malformed YAML front matter"]

    for k in REQUIRED_FIELDS:
        if k not in fm:
            errors.append(f"{path}: missing required field '{k}'")

    draft = fm.get("draft")
    if "draft" in fm and not isinstance(draft, bool):
        errors.append(f"{path}: 'draft' must be bool")

    title = fm.get("title")
    if "title" in fm and (not isinstance(title, str) or not title):
        errors.append(f"{path}: 'title' must be non-empty string")

    slug = fm.get("slug")
    if "slug" in fm:
        if not isinstance(slug, str) or not slug:
            errors.append(f"{path}: 'slug' must be non-empty string")
        else:
            expected = path.parent.name if path.name == "index.md" else path.stem
            if slug != expected:
                errors.append(
                    f"{path}: 'slug' ({slug!r}) must equal {'bundle dir' if path.name == 'index.md' else 'file stem'} ({expected!r})"
                )

    tags = fm.get("tags")
    if tags is not None and not _is_str_list(tags):
        errors.append(f"{path}: 'tags' must be list[str]")

    categories = fm.get("categories")
    if categories is not None and not _is_str_list(categories):
        errors.append(f"{path}: 'categories' must be list[str]")

    sid = fm.get("source_notion_id")
    if sid is not None and (not isinstance(sid, str) or not sid):
        errors.append(f"{path}: 'source_notion_id' must be non-empty string when present")

    return errors


def list_drafts(site_root: Path) -> list[Path]:
    """Return sorted paths of all Markdown posts with ``draft: true``.

    Tolerant to partial / malformed files — they are simply skipped. Both
    page-bundle (``<slug>/index.md``) and flat (``<slug>.md``) formats are
    scanned.
    """
    posts_dir = site_root.joinpath(*POSTS_SUBPATH)
    if not posts_dir.exists():
        return []
    drafts: list[Path] = []
    for md in sorted(posts_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_front_matter(text)
        if fm is None:
            continue
        if fm.get("draft") is True:
            drafts.append(md)
    return drafts


# --- internals ----------------------------------------------------------------


def _resolve_slug(posts_dir: Path, date: date_cls) -> str:
    base = date.isoformat()
    if not (posts_dir / base).exists():
        return base
    i = 2
    while (posts_dir / f"{base}-{i}").exists():
        i += 1
    return f"{base}-{i}"


def _render(fm: dict[str, Any], body: str) -> str:
    dumped = yaml.safe_dump(
        fm,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    body_tail = f"\n{body.rstrip()}\n" if body else ""
    return f"---\n{dumped}---\n{body_tail}"


def _parse_front_matter(text: str) -> dict[str, Any] | None:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            yaml_text = "\n".join(lines[1:i])
            try:
                data = yaml.safe_load(yaml_text)
            except yaml.YAMLError:
                return None
            return data if isinstance(data, dict) else None
    return None


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)
