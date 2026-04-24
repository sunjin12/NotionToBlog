---
description: 오늘(또는 지정일자) Notion Ready 일기를 Hugo 페이지 번들로 발행
argument-hint: [page_id?]
allowed-tools: Bash(python:*)
---

# /publish-today

Notion DB의 `Status == Ready` + 지정한 날짜(기본: 오늘 KST) 페이지를 `$HUGO_SITE_ROOT/content/posts/<slug>/index.md` 페이지 번들로 변환한다. 이미지는 Notion 서명 URL(만료 ~1h)에서 즉시 다운로드해 번들에 배치한다.

Idempotency (domain-notes §2 #1): 기존 번들의 `source_notion_id`가 같고 `lastmod ≥ Notion.last_edited_time`이면 **skip**. 더 오래됐으면 **update** 로 덮어쓴다. 다른 페이지가 그 slug를 점유 중이면 `-2`/`-3`…으로 자동 증분.

## 인자 해석

`$ARGUMENTS` 해석:

- 비어 있으면 오늘 KST의 모든 Ready 페이지를 대상으로 함
- 하이픈을 포함한 hex 토큰 (Notion page id 형태)이면 그 단일 페이지만 발행
- 그 외 형태면 사용자에게 확인을 묻는다 — 잘못된 id로 실행 회피

## 실행

```bash
python -X utf8 -m dayblog publish-today [--page-id <ID>] [--date YYYY-MM-DD]
```

출력 줄 형식: `<path>\t<status>\t(images=<n>)`. status ∈ `created` / `updated` / `skipped`. `WARN:` 접두사는 stderr에서 별도 수집.

## 보고 방식

- 성공한 항목을 다음과 같이 표로 요약:
  - 경로 → **마크다운 링크**로 (상대경로 변환)
  - status 색상 언어: `created`는 신규, `updated`는 갱신, `skipped`는 최신
- `WARN:` 행은 모두 "렌더러 경고" 섹션에 모아 전달 — unsupported block, front matter 문제 등
- 모두 `skipped`면 "오늘 새 변경 없음 (skip)"으로 요약
- 이미지가 1장 이상 다운로드된 경우 총 개수를 언급

## 실패 처리

- `NOTION_TOKEN`/`NOTION_DATABASE_ID` 누락 → `.env` 추가 안내
- `HUGO_SITE_ROOT` 누락 → 동일
- `error publishing <page_id>: ...` 줄은 그대로 사용자에게 전달 — 개별 페이지 실패는 다른 페이지 발행을 막지 않는다

## 사후 플로우

- 새 번들은 항상 `draft: true` 상태로 쓰여진다 (plan §3 결정). 사용자가 `hugo server`로 로컬 검증 후 `draft: false`로 플립, commit, push.
- `draft: true` 상태에서 push 시도 시 `.git/hooks/pre-push` + Claude PreToolUse 양쪽에서 차단된다.
