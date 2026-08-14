"""
The shared `AsyncGuardClient` every tool talks to.

One client is built for the life of the server and injected into tools with FastMCP's
`Shared` dependency. This allows a single `httpx` connection pool to be reused across
calls instead of initiating a new TLS handshake per tool invocation.

Building it can fail: `AsyncGuardClient` raises when the cloud engine is selected and no
API key resolves. That failure is captured rather than raised, because a server that
refuses to start reads as "the MCP server is broken" in a desktop client, with nothing
to say why. Instead, every tool call reports the real problem and names the variable to
set, and the `guard://config` resource shows what the server resolved.

Examples:
```python
    from fastmcp.dependencies import Shared
    from guard_mcp.client import GuardClientHandle, guard_client

    @mcp.tool
    async def my_tool(
        handle: GuardClientHandle = Shared(guard_client),
    ) -> str:
        client = handle.require()
        return client.base_url
    ```
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from guard_client import AsyncGuardClient, Engine, GuardError

from .errors import configuration_error

__all__ = ["GuardClientHandle", "guard_client"]

logger = logging.getLogger("guard_mcp")


class GuardClientHandle:
    """
    A built client, or the reason there isn't one.

    Attributes:
        client: The `AsyncGuardClient`, or `None` if construction failed.
        error: The `GuardError` that prevented construction, or `None`.
    """

    def __init__(
        self,
        client: Optional[AsyncGuardClient] = None,
        error: Optional[GuardError] = None,
    ) -> None:
        """
        Store whichever of the two outcomes occurred.

        Args:
            client: The client, when construction succeeded.
            error: The construction failure, when it did not.
        """
        self.client = client
        self.error = error

    @property
    def is_ready(self) -> bool:
        """
        Whether tools can run.

        Returns:
            True when a client was built.
        """
        return self.client is not None

    def require(self) -> AsyncGuardClient:
        """
        The client, or an error explaining how to configure the server.

        Returns:
            The `AsyncGuardClient` for this server.

        Raises:
            ToolError: No client could be built. The message names the environment
                variables that need setting.
        """
        if self.client is None:
            raise configuration_error(str(self.error) if self.error else None)
        return self.client

    def describe(self) -> dict[str, object]:
        """
        A redacted view of the resolved configuration, safe to hand to an agent.

        Returns:
            The engine, base URL, and readiness of the server. The API key is reported
            only as a boolean, never echoed.
        """
        if self.client is None:
            return {
                "ready": False,
                "error": str(self.error) if self.error else "unknown",
                "api_key_present": False,
            }
        return {
            "ready": True,
            "engine": self.client.engine.value,
            "base_url": self.client.base_url,
            "api_key_present": True,
            "local_engine_available": _local_engine_available(),
        }


def _local_engine_available() -> bool:
    """
    Whether the optional on-device engine can be imported.

    Returns:
        True when `guard_local` is installed. The import is attempted here rather than
        at module scope so the AGPL licensed engine is only ever loaded on demand.
    """
    try:
        import guard_local  # noqa: F401
    except Exception:
        return False
    return True


@asynccontextmanager
async def guard_client() -> AsyncIterator[GuardClientHandle]:
    """
    Build the shared client for the life of the server.

    Yields:
        A `GuardClientHandle` wrapping the client, or the error that prevented it.

    Notes:
        This is the factory passed to FastMCP's `Shared`, which caches it by function
        identity. Every tool that declares `Shared(guard_client)` therefore receives
        the same handle, and the client is closed once when the server shuts down.
    """
    handle: GuardClientHandle
    try:
        client = AsyncGuardClient()
    except GuardError as exc:
        logger.warning("Guard client unavailable: %s", exc)
        yield GuardClientHandle(error=exc)
        return

    handle = GuardClientHandle(client=client)
    engine = client.engine
    logger.info(
        "Guard client ready (engine=%s, base_url=%s)",
        engine.value,
        client.base_url if engine is Engine.CLOUD else "-",
    )
    try:
        yield handle
    finally:
        await client.aclose()
