"""Dayblog CLI — thin argparse layer over :mod:`dayblog.hugo`.

Invoke via ``python -X utf8 -m dayblog <subcommand>`` (see CLAUDE.md Windows
conventions). Loads ``.env`` from cwd so ``HUGO_SITE_ROOT`` resolves when
running from the repo root.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import hugo


def main(argv: list[str] | None = None) -> int:
    load_dotenv(override=False)
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dayblog", description="Notion → Hugo 일기 파이프라인")
    sub = p.add_subparsers(dest="cmd", required=True)

    new_p = sub.add_parser("new-post", help="Hugo 드래프트 페이지 번들 생성")
    new_p.add_argument("--site-root", help="Hugo 사이트 루트 (기본: $HUGO_SITE_ROOT)")
    new_p.add_argument("--date", help="YYYY-MM-DD; 미지정 시 오늘 KST")
    new_p.add_argument("--title", required=True, help="포스트 제목")
    new_p.add_argument("--tag", action="append", default=[], dest="tags", help="반복 가능")
    new_p.add_argument("--category", action="append", default=[], dest="categories")
    new_p.add_argument("--description")
    new_p.add_argument("--body", default="")
    new_p.add_argument("--not-draft", action="store_true", help="draft: false 로 생성 (비권장)")
    new_p.set_defaults(func=_cmd_new_post)

    list_p = sub.add_parser("list-drafts", help="draft: true 포스트 경로 나열")
    list_p.add_argument("--site-root")
    list_p.set_defaults(func=_cmd_list_drafts)

    val_p = sub.add_parser("validate", help="단일 포스트 front matter 검증")
    val_p.add_argument("path", help="index.md 또는 <slug>.md 경로")
    val_p.set_defaults(func=_cmd_validate)

    return p


def _resolve_site_root(override: str | None) -> Path:
    raw = override or os.environ.get("HUGO_SITE_ROOT")
    if not raw:
        print(
            "error: HUGO_SITE_ROOT not set. Either pass --site-root or add it to .env",
            file=sys.stderr,
        )
        sys.exit(2)
    path = Path(raw).expanduser()
    if not path.exists():
        print(f"error: site root does not exist: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def _cmd_new_post(args: argparse.Namespace) -> int:
    site = _resolve_site_root(args.site_root)
    try:
        d = date_cls.fromisoformat(args.date) if args.date else datetime.now(hugo.KST).date()
    except ValueError as exc:
        print(f"error: invalid --date ({exc})", file=sys.stderr)
        return 2

    path = hugo.new_post(
        site_root=site,
        date=d,
        title=args.title,
        tags=args.tags or None,
        categories=args.categories or None,
        description=args.description,
        body=args.body,
        draft=not args.not_draft,
    )
    print(path)
    errs = hugo.validate_front_matter(path)
    if errs:
        for e in errs:
            print(f"WARN: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_list_drafts(args: argparse.Namespace) -> int:
    site = _resolve_site_root(args.site_root)
    drafts = hugo.list_drafts(site)
    for p in drafts:
        print(p)
    if not drafts:
        print("(no drafts)", file=sys.stderr)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    errs = hugo.validate_front_matter(Path(args.path))
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
