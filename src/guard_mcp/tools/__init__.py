"""
Tool registration for the Guard MCP server.

Each module in this package exposes a `register(mcp)` function that attaches its tools
to a server instance, and `register_all` calls them in the order the tools should
appear. Registering through functions rather than at import time keeps the tools bound
to an explicit server, which is what makes the in-memory test client possible.

Examples:
    ```python
    from fastmcp import FastMCP
    from guard_mcp.tools import register_all

    mcp = FastMCP("guard")
    register_all(mcp)
    ```
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from ..settings import GuardMCPSettings
from . import catalog, feedback, moderation, predictions, spaces

__all__ = ["register_all"]


def register_all(mcp: FastMCP, settings: Optional[GuardMCPSettings] = None) -> None:
    """
    Attach every tool this server offers.

    Args:
        mcp: The server to register on.
        settings: Passed to the modules that need it. Only the moderation tools care,
            because whether `analyze_media` is a background task is a setting.
    """
    moderation.register(mcp, settings)
    predictions.register(mcp)
    spaces.register(mcp)
    catalog.register(mcp)
    feedback.register(mcp)
