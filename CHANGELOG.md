# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-04-25

Adds the `블로그` Heading 1 marker as a hard prerequisite for publication —
Dayblog now refuses to render the personal-diary portion of a Notion page.
Existing Hugo bundles are unaffected; the next `publish-today` for a
marker-less page returns `skipped-no-marker` and writes nothing.

### Added

- `dayblog.notion.render.slice_after_heading(blocks, title, *, level=1)` —
  returns ``(blocks_after_marker, marker_found)``. Pure function, top-level
  scan only (no recursion into toggles/callouts).
- `dayblog.notion.render.BLOG_SECTION_MARKER = "블로그"` — single source of
  truth for the marker text.
- `PublishResult.status` value `"skipped-no-marker"` for pages that lack
  the marker; the bundle path is reported but the file is not written.
- README "글 작성·수정 플로우" section walking through the new flow plus a
  troubleshooting entry for empty-publish results.
- domain-notes §9 freezing the marker contract (top-level only, KR text,
  case-sensitive, first-match wins).

### Changed (BREAKING)

- `publish_page` and `notion_render_markdown` now render **only the
  siblings after the first top-level Heading 1 ``블로그``**. Existing Notion
  pages must add the marker before their next `publish-today`; without it
  the publish is skipped (with a warning) so a forgotten marker can't leak
  diary content.

[Unreleased]: https://github.com/sunjin12/NotionToBlog/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/sunjin12/NotionToBlog/releases/tag/v0.2.0

## [0.1.0] - 2026-04-24

First end-to-end working release. Verified against a real Notion DB + PaperMod
Hugo site on Windows: four Ready pages published to page bundles, one
image fetched from a signed S3 URL, terminal `git push` blocked by the
`.git/hooks/pre-push` guard, idempotency transitions (`skipped` → `updated`)
confirmed.

### Added

- Hugo local tooling (`dayblog.hugo`): `new_post` / `validate_front_matter`
  / `list_drafts`, ISO-date slug with `-2`/`-3` collision suffix, YAML front
  matter with PaperMod-compatible fields (`title`, `date`, `lastmod`, `draft`,
  `slug`, `tags`, `categories`, `description`, `source_notion_id`).
- Notion adapter (`dayblog.notion`): `notion-client` wrapper with a
  2.5 req/s token bucket + `Retry-After` 429 retries, per-block Markdown
  renderer dispatching 16 Notion block types (paragraph · h1-3 · list · to-do
  · toggle · code · quote · callout · divider · image · equation · bookmark ·
  link_preview), and a hashed image collector (`sha1(page_id:block_id)[:10]`)
  stable across Notion's rotating signed URLs.
- FastMCP server (`dayblog_mcp`) exposing `notion_list_pages` /
  `notion_get_page` / `notion_render_markdown` tools. Registered via
  `.mcp.json` with `python -X utf8 -m dayblog_mcp`.
- Publish orchestration (`dayblog.publish`): idempotency keyed on
  `source_notion_id` + KST-normalized `lastmod`, slug collision handling that
  reuses the owning bundle's slug, and opt-in image download via an injected
  `http_get`.
- Double-guard push protection (`dayblog.hooks.pre_push_guard`): one scanner
  serves both Claude Code's `PreToolUse` hook (JSON deny on stdout) and git's
  native `pre-push` (exit 1 + stderr). Installed into the Hugo site repo via
  `python -X utf8 -m dayblog install-pre-push`.
- Slash commands: `/today`, `/publish-today`, `/publish-queue`, `/post-new`,
  `/draft-list`.
- CI: GitHub Actions matrix on Windows + Python 3.14 running `pytest` and
  `ruff check`.

### Fixed

- Route Notion queries through `data_sources.query` and resolve the
  `data_source_id` via `databases.retrieve` with per-database caching
  (`notion-client` 3.x / Notion API 2025-09-03 split databases into
  containers + data sources).
- `dayblog.hooks.pre_push_guard` now calls `load_dotenv(override=False)` from
  `main()` so `HUGO_SITE_ROOT` is discoverable without exporting into every
  shell.

### Notes

- Self-dogfood scope: Windows + Python 3.14 only, no PyPI upload.
- Test suite: 111 tests, CI target ≤60s.
- Domain decisions frozen in [docs/domain-notes.md](docs/domain-notes.md);
  any behavior change there must land alongside the corresponding test
  update.

[0.1.0]: https://github.com/sunjin12/NotionToBlog/releases/tag/v0.1.0
