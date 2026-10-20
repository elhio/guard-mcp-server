"""
Reading the catalog behind a space: detection targets and predictors.

A detection target is one thing the platform looks for, such as violence. A predictor is
the model that runs them. Both are read-only reference data, and both matter when an
agent needs to map a `target_id` in a result back to something it can name, or when it
is explaining why a space costs what it costs.

Examples:
    ```python
    page = await list_targets()
    print([item["name"] for item in page.items])
    ```
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.dependencies import Shared
from guard_client import GuardError

from ..client import GuardClientHandle, guard_client
from ..errors import to_tool_error
from ..schemas import ListPage
from ..utils import clamp_limit, to_page

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    """
    Attach the catalog tools to a server.

    Args:
        mcp: The server to register on.
    """

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def list_targets(
        limit: int = 20,
        skip: int = 0,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> ListPage:
        """
        List the detection targets the platform can run, such as violence or explicit.

        Args:
            limit: Page size, from 1 to 100.
            skip: How many records to skip, for paging.

        Returns:
            A page of targets with their ids, names and descriptions. These ids are what
            a cloud moderation result reports, and what submit_feedback and
            share_result expect.
        """
        client = handle.require()
        size = clamp_limit(limit)
        try:
            page = await client.targets.list(skip=skip, limit=size)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_page(page, skip=skip)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def list_predictors(
        limit: int = 20,
        skip: int = 0,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> ListPage:
        """
        List the predictors available to this account.

        Args:
            limit: Page size, from 1 to 100.
            skip: How many records to skip, for paging.

        Returns:
            A page of predictors with their token multipliers, supported media types
            and the detection targets each one can run.
        """
        client = handle.require()
        size = clamp_limit(limit)
        try:
            page = await client.predictors.list(skip=skip, limit=size)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_page(page, skip=skip)
