---
description: Hugo 드래프트 페이지 번들 스케폴드 생성 (Notion 없음, Phase 1)
argument-hint: [YYYY-MM-DD] <title...>
allowed-tools: Bash(python:*)
---

# /post-new

`$HUGO_SITE_ROOT/content/posts/<slug>/index.md` 페이지 번들을 만든다. Phase 1의 **수동 드래프트** 도구 — `source_notion_id` 없이 생성되며 `draft: true` 상태.

## 인자 해석

`$ARGUMENTS`를 다음 규칙으로 파싱:

1. 첫 토큰이 `^\d{4}-\d{2}-\d{2}$` 에 매치하면 날짜로 사용, 나머지 토큰을 제목으로 합친다.
2. 매치 안 하면 전체를 제목으로, 날짜는 오늘 (KST) 자동.
3. 인자 없거나 제목 비면 사용자에게 먼저 제목을 묻고 중단하지 말 것.

## 실행

```bash
python -X utf8 -m dayblog new-post --date "<DATE>" --title "<TITLE>"
```

`--date` 생략 시 CLI가 오늘 KST로 기본 처리. 추가 옵션이 사용자 문맥에 명확히 드러나면 붙인다:

- `--tag "일기" --tag "회고"` (반복 가능)
- `--category "일지"`
- `--description "짧은 요약"`
- `--body "초안 본문"` (대개 빈 채로 두고 편집기에서 채우는 편이 자연스럽다)

## 사후 처리

- CLI가 출력한 생성 경로를 사용자에게 **마크다운 링크로** 보고한다.
- stderr에 `WARN:` 항목이 있으면 그대로 전달 — validator가 검증했는데 발견한 문제라는 뜻.
- HUGO_SITE_ROOT 미설정 에러가 나면 레포 루트 `.env`에 `HUGO_SITE_ROOT=D:\vscodeprojects\blog`를 추가했는지 사용자에게 확인시켜라.

## 기본값 근거

- `slug` = ISO 날짜 (domain-notes.md §2 결정 #2)
- 복수 페이지 충돌 시 `-2`, `-3` 자동 접미사 (§2 #4)
- `categories` 기본 `["일지"]` (§3)
- 항상 `draft: true`로 시작 — 배포는 사용자가 수동으로 플립
