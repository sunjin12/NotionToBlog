"""NotionToBlog CLI — thin argparse layer over :mod:`dayblog.hugo`.

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

    pub_p = sub.add_parser(
        "publish-today",
        help="오늘 KST Notion Ready 페이지를 Hugo 번들로 발행",
    )
    pub_p.add_argument("--site-root")
    pub_p.add_argument("--page-id", help="단일 페이지만 발행 (지정 시 --date 무시)")
    pub_p.add_argument("--date", help="YYYY-MM-DD; 미지정 시 오늘 KST")
    pub_p.set_defaults(func=_cmd_publish_today)

    install_p = sub.add_parser(
        "install-pre-push",
        help="Hugo 레포에 .git/hooks/pre-push 가드 설치",
    )
    install_p.add_argument("--site-root")
    install_p.add_argument("--force", action="store_true", help="기존 훅 덮어쓰기")
    install_p.set_defaults(func=_cmd_install_pre_push)

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


def _cmd_publish_today(args: argparse.Namespace) -> int:
    site = _resolve_site_root(args.site_root)
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token:
        print("error: NOTION_TOKEN not set (add to .env)", file=sys.stderr)
        return 2
    if not db_id and not args.page_id:
        print("error: NOTION_DATABASE_ID not set (add to .env) or pass --page-id", file=sys.stderr)
        return 2

    # Lazy imports — these pull in notion-client/httpx, installed via `.[mcp]`.
    from dayblog.notion.client import NotionClient
    from dayblog.publish import publish_page

    client = NotionClient(token=token)

    if args.page_id:
        page_ids = [args.page_id]
    else:
        target_date = args.date or _today_kst_iso()
        page_ids = _query_ready_page_ids(client, db_id, target_date)
        if not page_ids:
            print(f"(no Ready pages for {target_date})", file=sys.stderr)
            return 0

    http_get = _build_http_get()
    exit_code = 0
    for pid in page_ids:
        try:
            result = publish_page(
                client=client, page_id=pid, site_root=site, http_get=http_get
            )
        except Exception as exc:
            print(f"error publishing {pid}: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        print(f"{result.path}\t{result.status}\t(images={result.image_count})")
        for w in result.warnings:
            print(f"WARN: {w}", file=sys.stderr)
    return exit_code


def _cmd_install_pre_push(args: argparse.Namespace) -> int:
    site = _resolve_site_root(args.site_root)
    hooks_dir = site / ".git" / "hooks"
    if not hooks_dir.exists():
        print(f"error: {hooks_dir} does not exist (not a git repo?)", file=sys.stderr)
        return 2
    target = hooks_dir / "pre-push"
    if target.exists() and not args.force:
        print(f"error: {target} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    target.write_text(_PRE_PUSH_HOOK, encoding="utf-8", newline="\n")
    try:
        import stat

        mode = target.stat().st_mode
        target.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    print(f"installed: {target}")
    return 0


# --- helpers -----------------------------------------------------------------


def _today_kst_iso() -> str:
    return datetime.now(hugo.KST).date().isoformat()


def _query_ready_page_ids(client, db_id: str, date_iso: str) -> list[str]:
    filter_ = {
        "and": [
            {"property": "Status", "select": {"equals": "Ready"}},
            {"property": "Date", "date": {"equals": date_iso}},
        ]
    }
    sorts = [{"property": "Date", "direction": "ascending"}]
    pages = client.query_database(db_id, filter=filter_, sorts=sorts)
    return [p["id"] for p in pages if p.get("id")]


def _build_http_get():
    import httpx

    def get(url: str) -> bytes:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.content

    return get


_PRE_PUSH_HOOK = """\
#!/bin/sh
# NotionToBlog pre-push guard — blocks push when any content/posts/*.md has draft:true.
# Installed by: python -X utf8 -m dayblog install-pre-push
exec python -X utf8 -m dayblog.hooks.pre_push_guard pre-push
"""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
