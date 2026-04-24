# Dayblog

Notion 일기 DB의 오늘자 페이지를 한 명령으로 Hugo(GitHub Pages) 포스트로 발행하는 개인용 파이프라인. **Self-dogfood 전용** — PyPI 배포 의도 없음, Windows + Python 3.14 단일 지원.

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  NotionToBlog (this)    │         │  Hugo site (external)    │
│  = Dayblog tool repo    │ writes  │  D:\vscodeprojects\blog  │
│  - src/dayblog/         │ ──────► │  - content/posts/<slug>/ │
│  - src/dayblog_mcp/     │         │  - themes/PaperMod/      │
│  - .claude/ hooks       │         │  - .git/hooks/pre-push   │
└─────────────────────────┘         └──────────────────────────┘
         ↑                                     ↑
  Claude Code harness                   hugo server + git push
  (Hook + Skill + MCP)                   (GH Pages 배포)
```

## 요구 사항

- Python **3.14**
- Windows (서브프로세스 · 경로 규약이 Windows 전제)
- Hugo **Extended** (PaperMod SCSS)
- Notion Integration 토큰 + 대상 DB ID + 통합이 DB에 초대됨
- 외부 Hugo 사이트 레포 (예: `D:\vscodeprojects\blog`) — PaperMod 테마가 sub-module로 등록돼 있으면 `git submodule update --init --recursive` 필수

## 설치

```bash
pip install -e .[mcp,dev]
```

`[mcp]` extra = `fastmcp`, `notion-client`, `httpx` (Notion 연동). `[dev]` = `pytest`, `ruff`. 최소 실행(네트워크 없는 Hugo 툴링만)은 core deps(`pyyaml`, `python-dotenv`)로 충분.

## 설정

레포 루트에 `.env` 작성:

```dotenv
NOTION_TOKEN=ntn_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
NOTION_DATABASE_ID=<32-hex, dashes optional>
HUGO_SITE_ROOT=D:\vscodeprojects\blog
```

Notion DB 스키마 요구사항 (docs/domain-notes.md §4):

| 속성 | 타입 | 필수 |
|---|---|---|
| `Title` (또는 `Name`) | title | ✅ |
| `Date` | date | ✅ |
| `Status` | select (`Draft` / `Ready` / `Published`) | ✅ |
| `Tags` | multi_select | ⭕ |
| `Category` | select | ⭕ |
| `Summary` | rich_text | ⭕ |

`/publish-today`는 **`Status == Ready`** 필터만 잡습니다.

## 실행

### CLI

```bash
python -X utf8 -m dayblog publish-today [--page-id <ID>] [--date YYYY-MM-DD]
python -X utf8 -m dayblog new-post --title "<제목>" [--date YYYY-MM-DD]
python -X utf8 -m dayblog list-drafts
python -X utf8 -m dayblog validate <path>
python -X utf8 -m dayblog install-pre-push    # Hugo 레포에 훅 설치
```

### Claude Code 슬래시 커맨드

- `/today` — 오늘자 Ready 페이지 목록 (진단)
- `/publish-today [page_id?]` — Notion → Hugo 번들 발행
- `/post-new [date?] <title>` — 수동 드래프트 스케폴드 (Notion 우회)
- `/draft-list` / `/publish-queue` — `draft: true` 포스트 나열

### MCP 툴 (`.mcp.json`이 자동 등록)

- `notion_list_pages(date?)` — Ready 페이지 요약 목록
- `notion_get_page(page_id)` — 원본 metadata + top-level blocks (진단용)
- `notion_render_markdown(page_id)` — Markdown + 이미지 매니페스트 + 경고

## Idempotency

`/publish-today`를 같은 날짜로 여러 번 돌려도 안전합니다 (domain-notes §2 #1):

- 기존 번들의 `source_notion_id`가 같고 `lastmod ≥ Notion.last_edited_time` → **skipped**
- 더 오래됐으면 → **updated** (덮어쓰기)
- 다른 페이지가 같은 날짜 slug를 점유 중이면 → **`-2`/`-3`/…** 로 자동 증분

## Draft 보호 (Double guard)

Dayblog는 `draft: true` 포스트가 실수로 GH Pages에 올라가는 걸 막기 위해 **두 훅을 동시에** 설치합니다:

### 1. `.git/hooks/pre-push` (터미널 `git push` 커버)

Hugo 레포에서 한 번:

```bash
cd D:\vscodeprojects\blog
python -X utf8 -m dayblog install-pre-push
```

설치 후 `git push` 시 pushed 범위 안에 draft 포스트가 있으면 exit 1로 차단하고 파일 경로를 stderr에 나열합니다.

### 2. Claude Code PreToolUse (Claude가 내는 Bash 커버)

`.claude/settings.json`에 등록돼 있음. Claude가 `git push` Bash 툴을 호출할 때 JSON deny로 차단합니다. **중요: 이 훅은 `HUGO_SITE_ROOT`를 읽어서 그 레포를 스캔**합니다 — `.env`에 제대로 세팅돼 있어야 작동.

### 왜 둘 다인가

Claude Code PreToolUse 훅은 구조적으로 "Claude가 Bash 툴로 실행하는" push만 가로챕니다. 사용자가 직접 터미널에서 `git push`하면 이 훅은 호출되지 않습니다. 그래서 git의 네이티브 `pre-push`도 필수. 두 훅이 동일한 Python 모듈(`dayblog.hooks.pre_push_guard`)을 호출하므로 로직은 DRY.

### 훅 우회 (의도적 push)

draft를 유지한 채로도 push해야 할 (매우 드문) 경우:

- 터미널: `git push --no-verify`
- Claude: 세션에서 훅 비활성화 (권장하지 않음)

## 로컬 렌더 확인

```bash
cd D:\vscodeprojects\blog
hugo server -D
# baseURL 서브패스가 있으면 http://localhost:1313/blog/
```

`-D`는 drafts 포함. 플립 전에 로컬에서 한 번 보고 `draft: false`로 바꿔 push.

## 범위 외

- PyPI 배포 (self-dogfood 전제)
- 과거 Notion 일기 일괄 마이그레이션
- Notion DB 역방향 동기화 (블로그 → Notion)
- Windows 외 OS, Python 3.14 외 버전
- Subagent / Plugin / Scheduled task / Status line (일부러 깊이 제한)

## 테스트

```bash
pytest              # 111+ tests
pytest -k smoke
ruff check src tests
```

## 문서

- [docs/domain-notes.md](docs/domain-notes.md) — 모든 도메인 결정의 단일 출처
- [CLAUDE.md](CLAUDE.md) — 이 레포에서 Claude Code가 지켜야 할 규약
- [CHANGELOG.md](CHANGELOG.md) — 변경 내역

## 라이선스

MIT (Private :: Do Not Upload — PyPI 배포 금지).
