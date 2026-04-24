---
description: 오늘자(KST) Notion 일기 Ready 페이지를 dayblog MCP로 나열 (진단용)
allowed-tools: mcp__dayblog__notion_list_pages
---

# /today

Notion DB에서 **오늘 날짜(KST) + `Status == Ready`**에 해당하는 일기 페이지를 MCP 툴 `notion_list_pages`로 조회한다. `/publish-today` (Phase 3)의 드라이런 / 사전 점검 용도.

## 실행

```
notion_list_pages()  # 인자 생략 → 오늘 KST로 자동
```

## 보고 방식

결과가 1건 이상이면 각 항목을 다음 포맷으로 출력:

```
- {title}  ({id})
  date: {date}  ·  status: {status}  ·  last_edited: {last_edited_time}
```

결과가 0건이면 다음을 차례대로 사용자에게 확인시킨다:

1. Notion DB에서 오늘자 페이지의 `Status`가 `Ready`인가? (`Draft`이면 안 잡힌다.)
2. `Date` property가 오늘 KST(`+09:00`) 기준인가? 다른 날짜 선택 시 `/today YYYY-MM-DD` 대신 `notion_list_pages(date="...")`를 직접 호출해 확인 가능.
3. 도메인 스키마 (`docs/domain-notes.md` §4) 와 실제 DB 속성 이름이 일치하는가? (`Title`, `Date`, `Status` 필수)

## 실패 처리

툴 호출이 실패하면 사용자에게 알리고 다음을 점검하도록 안내:

- `.mcp.json`이 레포 루트에 존재하는가? 새 Claude Code 세션이 필요할 수 있다.
- `.env`에 `NOTION_TOKEN`, `NOTION_DATABASE_ID`가 세팅되어 있는가?
- Notion Integration이 해당 DB에 초대되어 있는가?

에러 메시지는 그대로 인용해 사용자가 스스로 원인을 확인할 수 있게 한다.
