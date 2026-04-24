"""git push guard hooks for Dayblog.

The single guard module :mod:`dayblog.hooks.pre_push_guard` serves both
Claude Code's ``PreToolUse`` hook (JSON stdin/stdout) and git's native
``pre-push`` hook (ref-line stdin + exit code) so a draft post is blocked
whether the push is initiated by Claude or by the user in the terminal.
"""
