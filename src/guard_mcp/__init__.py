"""
An MCP server that gives AI agents visual content moderation through Elhio's Guard API.

The server wraps `guard_client`, exposing its moderation lifecycle as MCP tools. The
slow part, waiting for a cloud analysis to finish, runs as a background task, so an
agent is never blocked on a poll loop.

Quick start:
    ```python
    from guard_mcp import create_server

    mcp = create_server()
    mcp.run()
    ```
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from .settings import GuardMCPSettings

__all__ = ["__version__", "create_server"]

try:
    __version__ = version("guard-mcp-server")
except PackageNotFoundError:  # pragma: running from an uninstalled checkout
    __version__ = "0.0.0+unknown"


def create_server(settings: Optional[GuardMCPSettings] = None) -> FastMCP:
    """
    Build a fully wired server instance.

    Args:
        settings: Overrides the process settings. Mainly used for testing.

    Returns:
        The `FastMCP` server, with every tool, resource, and middleware attached.

    Note:
        The import is deferred so that reading `guard_mcp.__version__` does not drag in
        FastMCP and the Guard client.
    """
    from .server import create_server as _create_server

    return _create_server(settings)
