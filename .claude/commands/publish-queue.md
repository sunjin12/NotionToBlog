---
description: 발행 대기열 — /publish-today로 만들어진 draft:true 번들을 모아 보여줌
allowed-tools: Bash(python:*)
---

# /publish-queue

Hugo 사이트의 `content/posts/` 아래에서 `draft: true` 인 포스트 전체를 나열한다. `/publish-today`가 갓 만든 번들도 여기 잡힌다 — 그래서 "발행 직전 대기열" 역할.

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
