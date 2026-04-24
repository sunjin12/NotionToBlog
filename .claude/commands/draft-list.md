---
description: 현재 Hugo 사이트의 draft:true 포스트 전체 나열
allowed-tools: Bash(python:*)
---

# /draft-list

`$HUGO_SITE_ROOT/content/posts/` 아래의 모든 `*.md` 중 front matter에 `draft: true`가 있는 파일 경로를 나열.

## 실행

```bash
python -X utf8 -m dayblog list-drafts
```

## 보고 방식

- stdout 경로 목록을 받아 **마크다운 링크**로 보고. 상대경로로 변환하면 클릭 가능한 링크가 되어 편집 플로우로 이어진다.
- stderr에 `(no drafts)`만 있으면 "draft 없음"으로 요약.
- 결과 개수를 함께 표시 ("드래프트 N개").

## 범위

- 페이지 번들(`<slug>/index.md`)과 플랫(`<slug>.md`) 둘 다 훑는다.
- 파싱 실패한 파일은 조용히 건너뛴다 — 진단이 필요하면 `/validate <path>`를 별도로 돌린다 (Phase 3 범위).
