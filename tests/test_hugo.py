from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from dayblog.hugo import (
    KST,
    HugoError,
    list_drafts,
    new_post,
    validate_front_matter,
)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "content" / "posts").mkdir(parents=True)
    return tmp_path


def _read_fm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, fm_text, _ = text.split("---\n", 2)
    return yaml.safe_load(fm_text)


def test_new_post_creates_page_bundle_at_iso_date(site):
    path = new_post(
        site_root=site,
        date=date(2026, 4, 20),
        title="2026년 4월 20일 일기",
        now=datetime(2026, 4, 20, 21, 15, 0, tzinfo=KST),
    )
    assert path == site / "content" / "posts" / "2026-04-20" / "index.md"
    assert path.exists()


def test_new_post_front_matter_matches_schema(site):
    path = new_post(
        site_root=site,
        date=date(2026, 4, 20),
        title="테스트",
        tags=["일기", "회고"],
        description="짧은 요약",
        now=datetime(2026, 4, 20, 21, 15, 0, tzinfo=KST),
    )
    fm = _read_fm(path)
    assert fm["title"] == "테스트"
    assert fm["date"] == "2026-04-20T21:15:00+09:00"
    assert fm["draft"] is True
    assert fm["slug"] == "2026-04-20"
    assert fm["tags"] == ["일기", "회고"]
    assert fm["categories"] == ["일지"]  # default
    assert fm["description"] == "짧은 요약"
    assert "source_notion_id" not in fm  # manual draft has none


def test_new_post_is_valid_when_validated(site):
    path = new_post(site_root=site, date=date(2026, 4, 20), title="hi")
    assert validate_front_matter(path) == []


def test_new_post_collision_appends_numeric_suffix(site):
    first = new_post(site_root=site, date=date(2026, 4, 20), title="first")
    second = new_post(site_root=site, date=date(2026, 4, 20), title="second")
    third = new_post(site_root=site, date=date(2026, 4, 20), title="third")
    assert first.parent.name == "2026-04-20"
    assert second.parent.name == "2026-04-20-2"
    assert third.parent.name == "2026-04-20-3"
    # slug field must track the directory name for each
    assert _read_fm(second)["slug"] == "2026-04-20-2"


def test_new_post_refuses_overwrite_when_index_pre_exists(site):
    # Simulate an index.md that landed by some other means in the resolved dir
    bundle = site / "content" / "posts" / "2026-04-20"
    bundle.mkdir(parents=True)
    (bundle / "index.md").write_text("sentinel", encoding="utf-8")
    # suffix loop should skip to -2 and succeed
    path = new_post(site_root=site, date=date(2026, 4, 20), title="x")
    assert path.parent.name == "2026-04-20-2"


def test_new_post_rejects_empty_title(site):
    with pytest.raises(HugoError, match="title"):
        new_post(site_root=site, date=date(2026, 4, 20), title="")


def test_new_post_writes_body_after_front_matter(site):
    path = new_post(
        site_root=site,
        date=date(2026, 4, 20),
        title="t",
        body="첫 문단\n\n둘째 문단",
    )
    text = path.read_text(encoding="utf-8")
    assert text.endswith("첫 문단\n\n둘째 문단\n")
    # ensure fence separates frontmatter from body
    assert text.count("---\n") == 2


def test_validate_rejects_missing_required_fields(site):
    bundle = site / "content" / "posts" / "bad"
    bundle.mkdir(parents=True)
    p = bundle / "index.md"
    p.write_text("---\ntitle: only title\n---\n", encoding="utf-8")
    errs = validate_front_matter(p)
    # missing: date, draft, slug
    joined = "\n".join(errs)
    assert "'date'" in joined
    assert "'draft'" in joined
    assert "'slug'" in joined


def test_validate_rejects_slug_mismatch(site):
    bundle = site / "content" / "posts" / "2026-04-20"
    bundle.mkdir(parents=True)
    p = bundle / "index.md"
    p.write_text(
        "---\n"
        "title: t\n"
        "date: 2026-04-20T00:00:00+09:00\n"
        "draft: true\n"
        "slug: wrong-slug\n"
        "---\n",
        encoding="utf-8",
    )
    errs = validate_front_matter(p)
    assert any("'slug'" in e and "bundle dir" in e for e in errs)


def test_validate_rejects_non_yaml_file(site):
    bundle = site / "content" / "posts" / "plain"
    bundle.mkdir(parents=True)
    p = bundle / "index.md"
    p.write_text("no front matter here\n", encoding="utf-8")
    assert validate_front_matter(p) == [f"{p}: missing or malformed YAML front matter"]


def test_validate_flat_format_slug_matches_stem(site):
    p = site / "content" / "posts" / "hello.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        "title: Hello\n"
        "date: 2024-01-01T00:00:00+09:00\n"
        "draft: false\n"
        "slug: hello\n"
        "---\n",
        encoding="utf-8",
    )
    assert validate_front_matter(p) == []


def test_list_drafts_returns_only_drafts(site):
    # draft
    a = new_post(site_root=site, date=date(2026, 4, 20), title="a")
    # published
    b = new_post(site_root=site, date=date(2026, 4, 21), title="b", draft=False)
    drafts = list_drafts(site)
    assert a in drafts
    assert b not in drafts


def test_list_drafts_empty_when_no_posts_dir(tmp_path):
    assert list_drafts(tmp_path) == []


def test_list_drafts_skips_malformed_files(site):
    new_post(site_root=site, date=date(2026, 4, 20), title="good")
    bad = site / "content" / "posts" / "broken"
    bad.mkdir(parents=True)
    (bad / "index.md").write_text("not a valid post", encoding="utf-8")
    drafts = list_drafts(site)
    assert len(drafts) == 1
    assert drafts[0].parent.name == "2026-04-20"
