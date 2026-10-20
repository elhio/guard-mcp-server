"""
Reading the spaces media can be analyzed in.

A space decides which detection targets run, which predictor backs them, and where its
own blur and hide thresholds sit. An agent choosing a `space_id` for `analyze_media`
looks here, as does one that wants to know what cut-offs this space applies to a score.

Creating spaces is deliberately absent. It is a billing-relevant, hard-to-undo
operation, and an agent has no business doing it on someone's behalf.

Examples:
    ```python
    detail = await get_space("2c1f...")
    print(detail["enabled_targets"])
    ```
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastmcp import FastMCP
from fastmcp.dependencies import Shared
from guard_client import GuardError

from ..client import GuardClientHandle, guard_client
from ..errors import to_tool_error
from ..schemas import ListPage
from ..utils import clamp_limit, to_dict, to_page

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    """
    Attach the space tools to a server.

    Args:
        mcp: The server to register on.
    """

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def list_spaces(
        is_public: Optional[bool] = None,
        limit: int = 20,
        skip: int = 0,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> ListPage:
        """
        List the spaces this account can analyze media in.

        Args:
            is_public: Restrict to public or private spaces.
            limit: Page size, from 1 to 100.
            skip: How many records to skip, for paging.

        Returns:
            A page of spaces, each with its id, name, and enabled target names.
        """
        client = handle.require()
        size = clamp_limit(limit)
        try:
            page = await client.spaces.list(is_public=is_public, skip=skip, limit=size)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_page(page, skip=skip)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def get_space(
        space_id: str,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> Dict[str, Any]:
        """
        Fetch one space, including the targets it runs and its score thresholds.

        Args:
            space_id: The space to read.

        Returns:
            The space with its enabled detection targets, predictor multiplier, maximum
            media size, and the blur and hide thresholds it applies to scores.
        """
        client = handle.require()
        try:
            detail = await client.spaces.get(space_id)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_dict(detail)
