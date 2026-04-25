# NotionToBlog — Claude Code 프로젝트 규약

본인 Notion 일기 DB의 오늘자 페이지를 한 명령으로 Hugo 블로그 포스트로 발행하는 self-dogfood 파이프라인. 대상 Hugo 레포는 `D:\vscodeprojects\blog` (PaperMod).

## 도메인 단일 출처

모든 도메인 결정은 [docs/domain-notes.md](docs/domain-notes.md)에 있다. 변경 시 관련 테스트/검증도 함께 갱신한다. 이 문서는 계약이며, Phase 0 이후 주요 결정을 소리 없이 바꾸지 않는다.

## 언어 · 런타임

- Python **3.14** 단일 지원. `requires-python = ">=3.14"`.
- 패키지: 단일 `pyproject.toml`. `pip install -e .[mcp,dev]`로 풀 설치.
- 인코딩: 모든 파일 UTF-8 (BOM 없음). 파일 I/O는 `encoding="utf-8"` 명시.

## Windows 규약

- 서브프로세스 호출: `subprocess.run(..., encoding="utf-8", errors="replace")` — cp949 회피.
- Python 실행: 훅 · MCP 런처 등 외부 실행은 `python -X utf8 -m <module>` 형태. `.sh` / shebang 의존 금지 (Git Bash 실행 불안정).
- 경로: `pathlib.Path` 사용. 문자열 경로 조작 금지.
- 줄바꿈: `.gitattributes` 없이도 git 기본값(`core.autocrlf`) 존중. 테스트 비교는 `splitlines()` 경유.

## 레이아웃

```
src/
  dayblog/            # 라이브러리 + hooks + commands 구현
  dayblog_mcp/        # FastMCP 서버 (Phase 2에서 채움)
tests/                # pytest 단위 · 통합 테스트
docs/
  domain-notes.md     # 확정 결정 (단일 출처)
.claude/
  settings.json       # Hook / permission / env 설정
  commands/           # 슬래시 커맨드 (Phase 1~)
.git/hooks/pre-push   # 터미널 push 가드 (Phase 3)
```

## 버전 식별

`dayblog.__version__`은 `importlib.metadata.version("dayblog")`에서 읽는다. `pyproject.toml`이 단일 출처. 하드코딩 금지.

## 커밋 · 태그 규약

- **Conventional Commits**: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:` 접두사.
- Phase 종료마다 `phase-N` 태그. Pre-Phase는 태그 없이 커밋만.
- 커밋 메시지는 "왜"를 담는다. "무엇"은 diff가 말한다.

## 테스트

- `pytest` 기본값. `filterwarnings = ["error"]` — 경고는 실패로 취급.
- Hermetic: Notion 호출은 `monkeypatch` 가짜 클라이언트로, 파일 시스템은 `tmp_path`로.
- 네트워크 · 실제 Notion · 실제 Hugo 레포 의존 테스트 금지.
- 성공 기준: 총 테스트 **≥50** (Phase 3 완료 시점), CI ≤60초.

## Secret 관리

- `NOTION_TOKEN` 등은 `.env`에만 (루트). `.gitignore`가 `.env` 커밋을 막는다.
- `.claude/settings.json` · `pyproject.toml` · 커밋 메시지 · 테스트 픽스처에 **절대 금지**.
- 테스트는 환경변수 대신 `monkeypatch.setenv` 사용.

## 외부 도구 제약

- `notion-client` (공식 SDK) 사용. `notion2md`는 **금지** (유지보수 부실, 자체 렌더러로 대체).
- HTTP: `httpx` (동기). 레이트 리밋 래퍼를 `src/dayblog/notion/client.py`에 캡슐화.
- Hugo 빌드는 NotionToBlog 범위 외 — 로컬 `hugo` CLI로 수동 실행.

## Claude Code 하네스

- Skill (슬래시 커맨드): `.claude/commands/*.md`. Phase 1부터 `/post-new`, `/draft-list` 등 추가.
- Hook: `.claude/settings.json`의 `PreToolUse`에 `git push` 가드 등록 (Phase 3). `.git/hooks/pre-push`와 **동일한 Python 모듈** 호출로 DRY.
- MCP: `src/dayblog_mcp/server.py` FastMCP 서버, `.mcp.json`으로 등록 (Phase 2).
- 범위 외: Subagent, Plugin, Scheduled task, Status line. 일부러 깊이를 제한.

## 자주 쓰는 명령

```bash
pip install -e .[mcp,dev]           # 전체 설치
pytest                              # 전체 테스트
pytest -k smoke                     # 스모크만
python -c "import dayblog; print(dayblog.__version__)"
```
