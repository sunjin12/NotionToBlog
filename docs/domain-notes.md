# Dayblog 도메인 노트

> 작성: 2026-04-20 · 상태: Pre-Phase 초안 · 다음 단계: Phase 0 스켈레톤 진입 시 잠금

이 문서는 **코드를 작성하기 전에** 확정해야 할 도메인 결정을 모은 단일 출처(single source of truth)다. Phase 0 이후 여기의 규칙이 바뀌면 반드시 영향받는 테스트·검증 항목을 갱신한다.

---

## 1. 레포지토리 관계

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  NotionToBlog (현재)    │         │  (사용자 Hugo 사이트)    │
│  = Dayblog 툴 레포      │  writes │  = content/posts/        │
│  - src/dayblog/         │ ──────► │  - themes/…              │
│  - .claude/             │         │  - config.toml           │
│  - pre-push hook        │         │  - static/…              │
└─────────────────────────┘         └──────────────────────────┘
       ↑                                      ↑
       │                                      │
   Claude Code                          로컬 hugo server
   Hook + Skill + MCP                    → git push (Pages 배포)
```

**Hugo 사이트 레포 경로**: `D:\vscodeprojects\blog` (확정 2026-04-24)

- 테마: **PaperMod** (submodule, `themes/PaperMod`). 레포 clone 시 `git submodule update --init` 필수
- 기본 언어: `ko`, 보조 언어: `en` (filename suffix `*.en.md` 방식. Dayblog는 **한국어만** 생성 — 영문은 수동 번역 시 `*.en.md`로 별도 생성)
- 기존 포스트 위치: `content/posts/hello.md` (flat 파일). Dayblog는 **페이지 번들**(`content/posts/<slug>/index.md`)로 생성 → Hugo는 두 형식 혼합 허용
- `buildDrafts = false`, `hasCJKLanguage = true`, goldmark `unsafe = true` (HTML 허용 — toggle/callout 매핑 정당화)
- GH Pages: `https://sunjin12.github.io/blog/`

Dayblog는 환경 변수 `HUGO_SITE_ROOT` 또는 `.env`의 동일 키로 타겟 경로를 받는다. 절대 하드코딩 금지.

---

## 2. 8개 확정 결정

| # | 영역 | 결정 | 근거 |
|---|------|------|------|
| 1 | **Idempotency** | 같은 날 `/publish-today` 재실행 시, 기존 파일이 있고 Notion `last_edited_time` ≤ 파일 mtime이면 **skip**. 더 새로우면 **덮어쓰기**. | 일기 수정 반영 + 재생성 사고 방지 |
| 2 | **Slug** | `YYYY-MM-DD` ISO 날짜 단일. 디렉터리명 = `content/posts/2026-04-20/`. | 일기 도메인은 날짜가 식별자로 충분. 한글 transliteration 미결정 회피 |
| 3 | **Date 소스** | Notion DB의 `Date` property 필수화. 없으면 에러. `created_time` 대체 **금지**. | 명시적 > 암묵적. 타임존 혼란 회피 |
| 4 | **충돌 처리** | 같은 `Date` 값을 가진 페이지가 복수면 Notion 정렬 순서대로 `-2`, `-3` 접미사. slug = `2026-04-20-2`. | 자동 진행이 사용자 간섭보다 마찰 낮음 |
| 5 | **이미지 레이아웃** | Hugo **페이지 번들**: `content/posts/<slug>/index.md` + `content/posts/<slug>/img-XXXX.ext`. Markdown 참조는 상대경로. | Hugo 이미지 처리(resize/WebP) 활용 가능, slug 이동 시 이미지도 함께 |
| 6 | **Front matter** | **YAML** (`---` fence). TOML 미사용. | 2026년 테마 대다수 기본값. `gray-matter` 류 도구도 YAML이 표준 |
| 7 | **Secret 관리** | `NOTION_TOKEN`은 레포 루트 `.env`에만. `.gitignore`에 `.env` 추가 필수. `.claude/settings.json`·`pyproject.toml`·커밋에 **절대 포함 금지**. | secret leak 1회 방지가 편의성보다 높음 |
| 8 | **Hugo 빌드 주체** | **로컬 `hugo` 실행 + 빌드 산출물 push**. Dayblog는 `content/posts/`만 채우고 이미지 다운로드까지 끝낸다. GH Actions 빌드 미도입. | 이미지 URL 만료(~1h) + 파이프라인 단순화. 본인이 매일 로컬 작업 전제 |

---

## 3. Hugo front matter 스키마

모든 `index.md`는 다음 스키마를 따른다. 필드 누락/타입 오류 시 `hugo.validate_front_matter()`가 거부.

```yaml
---
title: "2026년 4월 20일 일기"   # required · str · Notion 페이지 Title
date: 2026-04-20T21:15:00+09:00  # required · ISO 8601 · Notion Date property (KST)
lastmod: 2026-04-20T22:03:11+09:00 # optional · Notion last_edited_time
draft: false                     # required · bool · 최초 생성 시 true
tags: ["일기", "회고"]           # optional · list[str] · Notion Tags multi-select
categories: ["일지"]             # 기본값 ["일지"] (기존 블로그 컨벤션), Notion Category select 있으면 덮어씀
slug: "2026-04-20"               # required · str · 디렉터리명과 일치
description: "..."               # optional · str · Notion Summary rich_text (없으면 본문 첫 200자) · PaperMod/archetype 필드명
source_notion_id: "abc123…"      # optional · str · Notion page id (idempotency 키, dayblog 커스텀)
---
```

> 필드명 근거: 기존 `content/posts/hello.md`와 `archetypes/default.md`는 `description`을 쓴다(`summary` 아님). 기존 블로그의 `categories: ["일지"]` 컨벤션을 따른다. `source_notion_id`는 PaperMod가 무시하는 dayblog 커스텀 필드 — idempotency 판단용.

> `source_notion_id` 의미 (Phase 1에서 명확화): Phase 3 `/publish-today`가 Notion 페이지를 발행할 때 **반드시 세팅**. Phase 1 `/post-new`가 만드는 수동 드래프트에는 **없음** — 그 경우 idempotency는 적용 대상이 아니며 사용자 수작업 관리. 따라서 validator는 `source_notion_id` 존재 자체는 강제하지 않고, 존재할 때만 형식을 검사한다. Phase 3 로직이 Notion-sourced 경로에서 자체 보증한다.

- **Idempotency 키**: `source_notion_id` + `lastmod` 쌍으로 판단 (Notion-sourced 포스트에만).
- **시간대**: KST(`+09:00`) 고정. 사용자가 시차 여행 시 수동 조정.
- **검증 규칙**: `hugo.validate_front_matter()`는 required 필드 존재 + 타입 + `slug == dirname` 일치 + `source_notion_id` 형식 확인.

---

## 4. Notion DB 스키마 요구사항

`dayblog-journal` DB가 반드시 가져야 할 속성:

| 속성 이름 | 타입 | 필수 | 용도 |
|-----------|------|------|------|
| `Title` (기본) | title | ✅ | `title` front matter |
| `Date` | date | ✅ | `date` front matter · 쿼리 키 |
| `Status` | select (`Draft` / `Ready` / `Published`) | ✅ | `/publish-today`는 `Ready`만 대상. 발행 후 `Published`로 업데이트하는 역동기화는 범위 외 |
| `Tags` | multi_select | ⭕ | `tags` front matter |
| `Category` | select | ⭕ | `categories` front matter 단일 요소 |
| `Summary` | rich_text | ⭕ | `summary` front matter |

**쿼리 필터**: `Status == "Ready"` AND `Date == today(KST)`.
속성 누락 시 MCP 툴이 명확한 에러 메시지로 실패한다 — "Add property `Status` (select) to DB".

---

## 5. 블록 → Markdown 매핑 테이블

자체 렌더러(`src/dayblog/notion/render.py`)가 디스패치할 블록 타입 (Phase 2 범위).

| # | Notion 블록 | Markdown 출력 | 비고 |
|---|-------------|---------------|------|
| 1 | `paragraph` | `{rich_text}` + `\n\n` | 빈 문단은 `\n\n` 단독 |
| 2 | `heading_1` | `# {text}\n\n` | |
| 3 | `heading_2` | `## {text}\n\n` | |
| 4 | `heading_3` | `### {text}\n\n` | |
| 5 | `bulleted_list_item` | `- {text}\n` + 자식 들여쓰기 2-space | 재귀 |
| 6 | `numbered_list_item` | `1. {text}\n` | Markdown 자동 번호 |
| 7 | `to_do` | `- [x] ` / `- [ ] ` | `checked` 반영 |
| 8 | `toggle` | `<details><summary>{text}</summary>\n\n{children}\n\n</details>\n\n` | HTML 허용 (Hugo 기본) |
| 9 | `code` | ``` ```{lang}\n{text}\n``` ``` + `\n\n` | Notion `language` → 그대로. `plain text` → 빈 fence |
| 10 | `quote` | `> {text}\n\n` | 줄바꿈은 `> `로 이어감 |
| 11 | `callout` | `> **{icon}** {text}\n\n` | 이모지 + blockquote. 테마별 shortcode는 미도입 |
| 12 | `divider` | `---\n\n` | |
| 13 | `image` | `![{caption}](./img-{hash}.{ext})` | `images.py`가 다운로드 후 경로 주입 |
| 14 | `equation` | `$${expression}$$` + `\n\n` | KaTeX. 테마가 KaTeX 미지원이면 raw LaTeX |
| 15 | `bookmark` / `link_preview` | `[{url}]({url})` | 최소 처리 |

**미지원 블록** (Phase 2 범위 외, 경고 로그만 출력): `table`, `column_list`, `synced_block`, `child_page`, `child_database`, `embed`, `video`, `file`, `pdf`, `audio`, `breadcrumb`, `link_to_page`.

테이블은 일기 도메인에서 거의 안 쓰므로 후속 phase. 나오면 HTML `<table>` 라우트 고려.

**Rich text 인라인**:
- `bold` → `**x**`, `italic` → `*x*`, `strikethrough` → `~~x~~`, `code` → `` `x` ``, `underline` → `<u>x</u>`
- `link` → `[text](url)`
- `mention` (user/page/date) → plain text representation. 페이지 멘션은 Notion URL 그대로 링크.

---

## 6. 이미지 파이프라인

```
Notion block (image)
    ↓  signed S3 URL (만료 ~1h)
images.download(url, page_id, block_id)
    ↓
 content/posts/<slug>/img-<sha1[:10]>.<ext>
    ↓
 ![caption](./img-<hash>.<ext>) 참조
```

- **해시 입력**: `sha1(f"{page_id}:{block_id}")` 앞 10자 → `img-a1b2c3d4e5.png`. 블록 ID 안정성에 의존 (Notion이 블록 이동/복제 시 새 ID 부여 — 수용 가능).
- **확장자**: HTTP `Content-Type` 또는 URL path 에서 추출. 매핑 실패 시 `.bin` 저장 + 경고 로그.
- **재다운로드 회피**: 같은 파일명 이미 존재하면 skip.
- **이미지 크기 제한**: 없음 (Hugo가 post-processing). 다만 >20MB 시 경고 로그.

---

## 7. 레이트 리밋 + 재시도

- Notion API 공식 한도: **평균 3 req/s per integration**.
- 클라이언트 래퍼(`client.py`)는 **2.5 req/s 토큰 버킷** (안전 여유).
- HTTP 429 응답 시 `Retry-After` 헤더 존중, 최대 3회 재시도. 초과 시 예외.
- 테스트는 시간을 `monkeypatch`로 고정하여 결정론적.

---

## 8. 미결 사항 (Pre-Phase 완료 전 채울 것)

- [x] Hugo 사이트 레포 실제 경로 — `D:\vscodeprojects\blog` (PaperMod, 2026-04-24 확정)
- [x] Hugo 테마 — PaperMod (front matter: `title` / `date` / `draft` / `tags` / `categories` / `description` / `slug`)
- [x] 테스트 Notion Integration secret 생성 + DB ID 기록 (사용자 개인 노트에 보관, 2026-04-24)
- [x] 더미 페이지 3개 작성: (a) 일반 문단 + 중첩 리스트, (b) 이미지 1장 + 코드 블록, (c) 토글 1개 + 콜아웃
