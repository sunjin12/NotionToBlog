---
description: 잔존 draft:true 번들 큐 (수동 드래프트 + 손편집)
allowed-tools: Bash(python:*)
---

# /publish-queue

Hugo 사이트의 `content/posts/` 아래에서 `draft: true` 인 포스트 전체를 나열한다. Notion `/publish-today`는 더 이상 draft:true를 만들지 않으므로 (`Status == Ready`가 게이트 역할 — domain-notes §3), 이 큐에는 보통 `/post-new`로 만든 수동 스캐폴드 또는 손편집으로 draft:true가 된 잔존분만 잡힌다.

## 실행

```bash
python -X utf8 -m dayblog list-drafts
```

## 보고 방식

- 경로 목록을 **마크다운 링크**로 (상대경로 변환)
- 항목이 있으면 앞에 개수 표시 ("발행 대기 N개")
- 각 줄 뒤에 다음 힌트를 붙인다: "→ 검토 후 `draft: false` 플립 → commit + push"
- stderr에 `(no drafts)` 만 있으면 "대기열 없음 — 오늘 발행 완료"로 요약

## 파싱 실패 파일

malformed front matter 파일은 `list-drafts`가 조용히 건너뛴다. 사용자가 추가 점검을 원하면 `/validate <path>` (Phase 3 범위 외, Phase 1 `dayblog validate`) 를 별도로 돌릴 수 있음을 안내.
