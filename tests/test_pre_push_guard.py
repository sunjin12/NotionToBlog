"""Tests for :mod:`dayblog.hooks.pre_push_guard` — dual-mode git push guard.

Three layers are exercised:

1. **Parsing helpers** (``_is_draft``, ``_extract_front_matter``) — pure, YAML in → bool out.
2. **Entry points** (``claude_guard`` / ``pre_push_guard``) — IO logic with an
   injected fake scanner; no subprocess, no filesystem.
3. **Scanner integration** (``scan_range``) — a couple of end-to-end tests that
   build a real tmp git repo and commit real front-matter files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dayblog.hooks import pre_push_guard as guard
from dayblog.hooks.pre_push_guard import Violation

# --- pure helpers -------------------------------------------------------------


def test_is_draft_detects_true_in_front_matter():
    text = "---\ntitle: x\ndraft: true\n---\nbody"
    assert guard._is_draft(text) is True


def test_is_draft_false_for_draft_false():
    assert guard._is_draft("---\ntitle: x\ndraft: false\n---\n") is False


def test_is_draft_false_for_missing_draft_key():
    assert guard._is_draft("---\ntitle: x\n---\n") is False


def test_is_draft_false_for_no_front_matter():
    assert guard._is_draft("no front matter here") is False


def test_is_draft_false_for_malformed_yaml():
    assert guard._is_draft("---\n: : bad\n---\n") is False


# --- claude_guard -------------------------------------------------------------


def _fake_scanner(violations: list[Violation]):
    calls: list[tuple[Path, str]] = []

    def scan(root: Path, range_spec: str) -> list[Violation]:
        calls.append((root, range_spec))
        return violations

    scan.calls = calls  # type: ignore[attr-defined]
    return scan


def test_claude_guard_allows_when_stdin_is_empty():
    code, out = guard.claude_guard("", site_root=Path("."))
    assert code == 0 and out == ""


def test_claude_guard_allows_when_tool_is_not_bash():
    payload = {"tool_name": "Read", "tool_input": {}}
    code, out = guard.claude_guard(json.dumps(payload), site_root=Path("."))
    assert code == 0 and out == ""


def test_claude_guard_allows_non_push_bash_commands():
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
    code, out = guard.claude_guard(json.dumps(payload), site_root=Path("."))
    assert code == 0 and out == ""


def test_claude_guard_allows_when_site_root_is_none():
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    code, out = guard.claude_guard(json.dumps(payload), site_root=None)
    assert code == 0 and out == ""


def test_claude_guard_allows_when_site_root_is_not_a_git_repo(tmp_path: Path):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    code, out = guard.claude_guard(json.dumps(payload), site_root=tmp_path)
    assert code == 0 and out == ""


def test_claude_guard_allows_when_scanner_returns_no_violations(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    scan = _fake_scanner(violations=[])
    code, out = guard.claude_guard(json.dumps(payload), site_root=tmp_path, scan=scan)
    assert code == 0 and out == ""
    # The guard still attempted a scan exactly once.
    assert len(scan.calls) == 1


def test_claude_guard_denies_with_json_when_scanner_finds_drafts(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    scan = _fake_scanner(violations=[Violation(path="content/posts/x/index.md", reason="draft: true")])
    code, out = guard.claude_guard(json.dumps(payload), site_root=tmp_path, scan=scan)
    assert code == 0  # JSON decision, not a hard error exit
    decision = json.loads(out)
    assert decision["decision"] == "deny"
    assert "content/posts/x/index.md" in decision["reason"]


def test_claude_guard_tolerates_malformed_json_stdin():
    code, out = guard.claude_guard("{not valid", site_root=Path("."))
    assert code == 0 and out == ""


# --- pre_push_guard -----------------------------------------------------------


def test_pre_push_guard_allows_empty_stdin(tmp_path: Path):
    code, reason = guard.pre_push_guard("", repo_root=tmp_path)
    assert code == 0 and reason == ""


def test_pre_push_guard_skips_delete_refs(tmp_path: Path):
    # zero local_sha ⇒ user is deleting the remote branch; pass through.
    zero = "0" * 40
    line = f"(delete) {zero} refs/heads/foo {'a' * 40}"
    scan = _fake_scanner(violations=[])
    code, reason = guard.pre_push_guard(line + "\n", repo_root=tmp_path, scan=scan)
    assert code == 0 and reason == ""
    assert scan.calls == []  # never invoked the scanner


def test_pre_push_guard_uses_local_sha_alone_for_new_branch(tmp_path: Path):
    zero = "0" * 40
    local = "a" * 40
    line = f"refs/heads/new {local} refs/heads/new {zero}"
    scan = _fake_scanner(violations=[])
    guard.pre_push_guard(line + "\n", repo_root=tmp_path, scan=scan)
    assert scan.calls == [(tmp_path, local)]


def test_pre_push_guard_uses_range_for_fast_forward(tmp_path: Path):
    remote = "b" * 40
    local = "a" * 40
    line = f"refs/heads/main {local} refs/heads/main {remote}"
    scan = _fake_scanner(violations=[])
    guard.pre_push_guard(line + "\n", repo_root=tmp_path, scan=scan)
    assert scan.calls == [(tmp_path, f"{remote}..{local}")]


def test_pre_push_guard_denies_with_nonzero_exit_on_violations(tmp_path: Path):
    remote = "b" * 40
    local = "a" * 40
    line = f"refs/heads/main {local} refs/heads/main {remote}"
    scan = _fake_scanner(
        violations=[Violation(path="content/posts/abc/index.md", reason="draft: true")]
    )
    code, reason = guard.pre_push_guard(line + "\n", repo_root=tmp_path, scan=scan)
    assert code == 1
    assert "content/posts/abc/index.md" in reason
    assert "Flip `draft: false`" in reason


def test_pre_push_guard_dedupes_violations_across_refs(tmp_path: Path):
    line1 = f"refs/heads/a {'a'*40} refs/heads/a {'b'*40}"
    line2 = f"refs/heads/b {'c'*40} refs/heads/b {'d'*40}"
    dupe = Violation(path="content/posts/same/index.md", reason="draft: true")
    scan = _fake_scanner(violations=[dupe])  # returned for every call
    code, reason = guard.pre_push_guard(f"{line1}\n{line2}\n", repo_root=tmp_path, scan=scan)
    assert code == 1
    assert reason.count("content/posts/same/index.md") == 1


# --- scan_range integration (real git) ---------------------------------------


def _git(repo: Path, *args: str, **env: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**_base_env(), **env} if env else None,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stderr}")
    return result.stdout


def _base_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="dayblog-test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="dayblog-test",
        GIT_COMMITTER_EMAIL="test@example.com",
    )
    return env


def _init_repo_with_commits(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a tmp git repo with two commits: first has draft:false, second adds draft:true."""
    repo = tmp_path / "site"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "content" / "posts" / "okay").mkdir(parents=True)
    (repo / "content" / "posts" / "okay" / "index.md").write_text(
        "---\ntitle: okay\ndraft: false\nslug: okay\ndate: 2026-04-24\n---\nbody\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add ok post")
    base_sha = _git(repo, "rev-parse", "HEAD").strip()

    (repo / "content" / "posts" / "draftp").mkdir(parents=True)
    (repo / "content" / "posts" / "draftp" / "index.md").write_text(
        "---\ntitle: d\ndraft: true\nslug: draftp\ndate: 2026-04-24\n---\nbody\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add draft post")
    tip_sha = _git(repo, "rev-parse", "HEAD").strip()

    return repo, base_sha, tip_sha


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_scan_range_detects_draft_true_in_diff(tmp_path: Path):
    repo, base, tip = _init_repo_with_commits(tmp_path)
    violations = guard.scan_range(repo, f"{base}..{tip}")
    assert [v.path for v in violations] == ["content/posts/draftp/index.md"]


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_scan_range_returns_empty_for_clean_history(tmp_path: Path):
    repo, base, _ = _init_repo_with_commits(tmp_path)
    # Range base..base ⇒ empty diff ⇒ no violations.
    violations = guard.scan_range(repo, f"{base}..{base}")
    assert violations == []
