"""Notion domain layer — client wrapper, block → Markdown renderer, image pipeline.

This subpackage is independent of :mod:`dayblog_mcp` — the MCP server layers on top
but the core is importable and testable without FastMCP/notion-client installed
(tests substitute duck-typed fakes).
"""
