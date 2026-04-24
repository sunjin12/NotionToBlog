"""Dual-mode git-push guard blocking ``draft: true`` posts.

Two invocation modes share one scanner:

- ``claude``   — reads a Claude Code ``PreToolUse`` JSON payload from stdin
                 and emits a ``{"decision": "deny", "reason": "..."}`` JSON
                 to stdout when draft posts are about to be pushed.
- ``pre-push`` — reads git's ``<local_ref> <local_sha> <remote_ref>
                 <remote_sha>`` lines from stdin and exits non-zero with a
                 human-readable reason on stderr. Installed as
                 ``.git/hooks/pre-push`` inside the Hugo site repo.

The plan (§"Double guard") calls for both ends because Claude's PreToolUse
hook cannot see pushes initiated directly in the user's terminal.

The scanner (:func:`scan_range`) is injected into both entry points so tests
can exercise the IO/parsing logic without spinning up a real git repo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

SCAN_DIFF_ARGS = ("--name-only", "--diff-filter=d")
POST_PATH_RE = re.compile(r"^content/posts/.+\.md$")


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str  # human-readable ("draft: true")


ScanFn = Callable[[Path, str], list[Violation]]


# --- core scanner -------------------------------------------------------------


def scan_range(repo_root: Path, range_spec: str) -> list[Violation]:
    """Return every post in ``range_spec`` whose tip-revision front matter has
    ``draft: true``.

    A ``range_spec`` of ``"<sha>"`` (single rev, used for first-push of a new
    branch) is accepted — git treats that as the full reachability set.
    """
    diff = _git(
        repo_root, "diff", *SCAN_DIFF_ARGS, range_spec,
    )
    if diff is None:
        return []
    changed = [line.strip() for line in diff.splitlines() if line.strip()]
    posts = [p for p in changed if POST_PATH_RE.match(p)]
    tip = range_spec.split("..")[-1] if ".." in range_spec else range_spec
    violations: list[Violation] = []
    for path in posts:
        blob = _git(repo_root, "show", f"{tip}:{path}")
        if blob is None:
            continue
        if _is_draft(blob):
            violations.append(Violation(path=path, reason="draft: true"))
    return violations


def _git(repo_root: Path, *args: str) -> str | None:
    """Run ``git -C <root> <args>``; return stdout text or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _is_draft(blob: str) -> bool:
    fm = _extract_front_matter(blob)
    if fm is None:
        return False
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and data.get("draft") is True


def _extract_front_matter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i])
    return None


# --- Claude PreToolUse mode ---------------------------------------------------


def claude_guard(
    stdin_text: str,
    *,
    site_root: Path | None,
    scan: ScanFn = scan_range,
) -> tuple[int, str]:
    """Decide allow/deny for a Claude ``PreToolUse`` event.

    Returns ``(exit_code, stdout_text)``. When blocking, writes a JSON decision
    object to stdout — Claude honors this regardless of exit code, so we keep
    the exit code at 0 (non-zero would also be treated as a tool-execution
    error by unrelated machinery).
    """
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return 0, ""

    if payload.get("tool_name") != "Bash":
        return 0, ""
    cmd = ((payload.get("tool_input") or {}).get("command") or "").strip()
    if not _is_git_push(cmd):
        return 0, ""
    if site_root is None:
        return 0, ""  # nothing to protect — user hasn't configured HUGO_SITE_ROOT
    if not (site_root / ".git").exists():
        return 0, ""

    range_spec = _infer_push_range(cmd, site_root) or "@{u}..HEAD"
    violations = scan(site_root, range_spec)
    if not violations:
        return 0, ""
    decision = {"decision": "deny", "reason": _format_reason(violations)}
    return 0, json.dumps(decision)


def _is_git_push(cmd: str) -> bool:
    # Match "git push" allowing for leading `-C <dir>` / `-c k=v` etc.
    return bool(re.search(r"\bgit\s+(?:-[cC]\s+\S+\s+)*push\b", cmd))


def _infer_push_range(cmd: str, repo_root: Path) -> str | None:
    tokens = cmd.split()
    try:
        i = tokens.index("push")
    except ValueError:
        return None
    rest = [t for t in tokens[i + 1:] if not t.startswith("-")]
    remote = rest[0] if rest else "origin"
    branch = rest[1] if len(rest) > 1 else _current_branch(repo_root)
    if not branch:
        return None
    return f"{remote}/{branch}..HEAD"


def _current_branch(repo_root: Path) -> str | None:
    out = _git(repo_root, "branch", "--show-current")
    if out is None:
        return None
    out = out.strip()
    return out or None


# --- git pre-push mode --------------------------------------------------------


def pre_push_guard(
    stdin_text: str,
    *,
    repo_root: Path,
    scan: ScanFn = scan_range,
) -> tuple[int, str]:
    """Decide allow/deny for a git ``pre-push`` invocation.

    stdin is one line per ref being pushed:
    ``<local_ref> <local_sha> <remote_ref> <remote_sha>``. A
    zero-sha ``local_sha`` means the user is deleting that remote ref — we
    let those through.

    Returns ``(exit_code, stderr_text)``. Non-zero exit aborts the push.
    """
    all_violations: list[Violation] = []
    for raw_line in stdin_text.splitlines():
        parts = raw_line.split()
        if len(parts) < 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts[:4]
        if _is_zero_sha(local_sha):
            continue
        range_spec = f"{remote_sha}..{local_sha}" if not _is_zero_sha(remote_sha) else local_sha
        all_violations.extend(scan(repo_root, range_spec))

    if not all_violations:
        return 0, ""
    # Dedupe by path — a file touched in multiple refs would otherwise repeat.
    seen: set[str] = set()
    unique: list[Violation] = []
    for v in all_violations:
        if v.path not in seen:
            seen.add(v.path)
            unique.append(v)
    return 1, _format_reason(unique)


def _is_zero_sha(sha: str) -> bool:
    return bool(sha) and set(sha) == {"0"}


# --- formatting ---------------------------------------------------------------


def _format_reason(violations: list[Violation]) -> str:
    lines = ["[dayblog] draft posts detected in this push — aborting:"]
    for v in violations:
        lines.append(f"  - {v.path}  ({v.reason})")
    lines.append("")
    lines.append("Flip `draft: false` in the file(s) above, commit, and re-push.")
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="dayblog.hooks.pre_push_guard",
        description="Block git push when draft:true posts are in the pushed range.",
    )
    parser.add_argument("mode", choices=("claude", "pre-push"))
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo to scan (default: $HUGO_SITE_ROOT for claude, cwd for pre-push).",
    )
    args = parser.parse_args(argv)

    stdin_text = sys.stdin.read()

    if args.mode == "claude":
        root = args.repo_root or _env_site_root()
        code, out = claude_guard(stdin_text, site_root=root)
        if out:
            sys.stdout.write(out)
        return code

    root = args.repo_root or Path.cwd()
    code, reason = pre_push_guard(stdin_text, repo_root=root)
    if reason:
        sys.stderr.write(reason + "\n")
    return code


def _env_site_root() -> Path | None:
    raw = os.environ.get("HUGO_SITE_ROOT")
    return Path(raw) if raw else None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
