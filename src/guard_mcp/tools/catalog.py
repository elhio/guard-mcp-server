"""
Reading the catalog behind a space: detection tasks and predictors.

A detection task is one thing the platform looks for, such as violence. A predictor is
the model that runs them. Both are read-only reference data, and both matter when an
agent needs to map a `task_id` in a result back to something it can name, or when it is
explaining why a space costs what it costs.

The tool is called `list_detection_tasks` rather than `list_tasks` on purpose. MCP has
its own notion of a background task, and two unrelated meanings of the same word in one
tool list is a reliable way to confuse a model.

Examples:
    ```python
    page = await list_detection_tasks()
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
    async def list_detection_tasks(
        limit: int = 20,
        skip: int = 0,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> ListPage:
        """
        List the detection tasks the platform can run, such as violence or explicit.

        Args:
            limit: Page size, from 1 to 100.
            skip: How many records to skip, for paging.

        Returns:
            A page of tasks with their ids, names and descriptions. These ids are what
            a cloud moderation result reports, and what submit_feedback and
            share_result expect.
        """
        client = handle.require()
        size = clamp_limit(limit)
        try:
            page = await client.tasks.list(skip=skip, limit=size)
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
            and the detection tasks each one can run.
        """
        client = handle.require()
        size = clamp_limit(limit)
        try:
            page = await client.predictors.list(skip=skip, limit=size)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_page(page, skip=skip)
