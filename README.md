# NotionToBlog

Notion 일기 DB의 오늘자 페이지를 한 명령으로 Hugo(GitHub Pages) 포스트로 발행하는 개인용 파이프라인. **Self-dogfood 전용** — PyPI 배포 의도 없음, Windows + Python 3.14 단일 지원. (내부 패키지 식별자는 `dayblog` / `dayblog_mcp`.)

## Highlights

- Notion 일기 → Hugo + GH Pages 자동 발행 — 두 차례 후속 릴리스(v0.2.0 / v0.2.1)로 실사용 피드백을 반영한 실가동 도구
- Claude Code의 **Hook + Skill + MCP** 3축을 의도적으로 한정 적용 (Subagent / Plugin / Scheduled task는 범위 외) — 깊이를 위해 너비를 포기한 설계
- **124 tests** · GitHub Actions CI · Notion API 2025-09-03 (`data_sources.query`) 마이그레이션 대응
- 핵심 설계 결정과 트레이드오프는 [docs/domain-notes.md](docs/domain-notes.md)에 한 페이지로 정리 — commit history 자체가 곧 개발 일지

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  NotionToBlog (this)    │         │  Hugo site (external)    │
│  - src/dayblog/         │ writes  │  D:\vscodeprojects\blog  │
│  - src/dayblog_mcp/     │ ──────► │  - content/posts/<slug>/ │
│  - .claude/ hooks       │         │  - themes/PaperMod/      │
│                         │         │  - .git/hooks/pre-push   │
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

## 글 작성·수정 플로우

### 새 글 발행

1. Notion `dayblog-journal` DB에서 오늘자 페이지 작성 (Date / Title / 일기 본문)
2. 페이지 맨 아래에 **Heading 1 `블로그`** 추가 → 그 아래 블로그용 내용 작성 (이 마커가 없으면 발행이 거부됨, domain-notes §9)
3. `Status` 를 `Ready` 로 변경
4. `python -X utf8 -m dayblog publish-today` (또는 Claude `/publish-today`) — `created` 또는 `updated` 출력
5. `hugo server` → 로컬 프리뷰 확인 (`-D` 불필요, baseURL이 서브패스면 `http://localhost:1313/blog/`)
6. `git add -A && git commit -m "post: <slug>" && git push` — pre-push 훅이 손편집 draft 검사 후 GH Pages 자동 배포

Notion `Status == Ready`가 이미 발행 게이트 역할을 하므로 publish-today는 항상 `draft: false`로 직행 — 수동 플립 단계 없음.

### 발행된 글 수정

1. Notion에서 본문 수정 → `last_edited_time` 자동 갱신
2. `python -X utf8 -m dayblog publish-today` → idempotency가 `updated`로 감지, 번들 덮어씀
3. `git diff` 확인 → commit + push

### 삭제

- Notion `Status` → `Draft`: 이후 `publish-today` 대상에서 빠짐 (기존 번들은 손대지 않음)
- 블로그에서도 지우려면 Hugo 레포의 해당 번들 디렉토리를 수동 삭제 후 commit + push

### 트러블슈팅: 빈 포스트가 나옴

- 결과가 `skipped-no-marker` 면 Notion 페이지 본문에 **top-level Heading 1 `블로그`** 마커가 없음. toggle/callout 안의 H1은 인식 안 함 — 페이지 최상위 형제로 둬야 함.
- `Title`/`Date`/`Status` property 이름이 정확히 매치되는지 (`Status == Ready`).

## Idempotency

`/publish-today`를 같은 날짜로 여러 번 돌려도 안전합니다 (domain-notes §2 #1):

- 기존 번들의 `source_notion_id`가 같고 `lastmod ≥ Notion.last_edited_time` → **skipped**
- 더 오래됐으면 → **updated** (덮어쓰기)
- 다른 페이지가 같은 날짜 slug를 점유 중이면 → **`-2`/`-3`/…** 로 자동 증분

## Draft 보호 (Double guard)

NotionToBlog는 `draft: true` 포스트가 실수로 GH Pages에 올라가는 걸 막기 위해 **두 훅을 동시에** 설치합니다. (Notion publish-today는 이미 `draft: false`로 직행하므로 자동 발행 흐름에서는 차단되지 않습니다 — 훅은 `/post-new`로 만든 수동 드래프트 + 손편집으로 draft:true가 된 포스트 보호 용도.)

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
