"""Sanity tests for ``dayblog_mcp.server`` — import + tool registration.

Does not spin up the MCP runtime or touch Notion. Verifies:

- the module imports cleanly (so a missing dep or typo fails CI fast);
- the three expected tools are registered under their public names.
"""

from __future__ import annotations

import asyncio


def test_server_registers_three_expected_tools():
    import dayblog_mcp.server as srv

    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert {"notion_list_pages", "notion_get_page", "notion_render_markdown"}.issubset(names)


def test_server_exposes_main_entrypoint():
    import dayblog_mcp.server as srv

    assert callable(srv.main)
