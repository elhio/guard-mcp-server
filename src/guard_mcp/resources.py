"""
Read-only views an agent can pull without spending a tool call.

The `guard://config` resource exists for one reason: when something is misconfigured,
the agent needs to be able to see *what* the server resolved without being told. It
reports whether an API key was found, never the key itself.

The `guard://spaces` resource is the same data `list_spaces` returns, offered as a
resource for clients that prefer to attach reference material to a conversation rather
than call a tool for it.

Examples:
    ```python
    content = await client.read_resource("guard://config")
    ```
"""

from __future__ import annotations

from typing import Any, Dict

from fastmcp import FastMCP
from fastmcp.dependencies import Shared
from guard_client import GuardError

from .client import GuardClientHandle, guard_client
from .errors import to_tool_error
from .settings import get_settings
from .utils import to_dict

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    """
    Attach the resources to a server.

    Args:
        mcp: The server to register on.
    """

    @mcp.resource("guard://config", mime_type="application/json")
    async def config(
        handle: GuardClientHandle = Shared(guard_client),
    ) -> Dict[str, Any]:
        """
        What this server resolved at startup, with secrets redacted.

        Returns:
            Whether a Guard client could be built, which engine and base URL it uses,
            whether the on-device engine is installed, and the media directories the
            server will read from. The API key is reported only as a boolean.
        """
        settings = get_settings()
        return {
            "guard_client": handle.describe(),
            "media_roots": [str(root) for root in settings.resolved_media_roots()],
            "allow_any_path": settings.allow_any_path,
            "max_media_bytes": settings.max_media_bytes,
            "default_poll_timeout": settings.default_poll_timeout,
        }

    @mcp.resource("guard://spaces", mime_type="application/json")
    async def spaces(
        handle: GuardClientHandle = Shared(guard_client),
    ) -> Dict[str, Any]:
        """
        The spaces this account can analyze media in.

        Returns:
            Every space, with its id, name, and enabled task names.
        """
        client = handle.require()
        try:
            page = await client.spaces.list(limit=100)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return {"spaces": [to_dict(space) for space in page.data], "count": page.count}
