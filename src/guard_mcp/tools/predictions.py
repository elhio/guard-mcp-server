"""
Reading predictions that already exist.

These tools are how an agent picks up work it could not wait for. When
`analyze_media` times out it says which prediction id to come back to; `get_prediction`
is where it comes back to. `list_predictions` covers the review case, where someone
wants to know what has been moderated recently and how it went.

Examples:
    ```python
    summary = await get_prediction("0b3c...")
    if summary.status == "completed":
        print([item.score for item in summary.results])
    ```
"""

from __future__ import annotations

from typing import List, Optional

from fastmcp import FastMCP
from fastmcp.dependencies import Shared
from guard_client import GuardError

from ..client import GuardClientHandle, guard_client
from ..errors import to_tool_error
from ..schemas import ListPage, PredictionSummary
from ..utils import clamp_limit, to_page, to_prediction_summary

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    """
    Attach the prediction tools to a server.

    Args:
        mcp: The server to register on.
    """

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def get_prediction(
        prediction_id: str,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> PredictionSummary:
        """
        Fetch one prediction and the scores it produced.

        Args:
            prediction_id: The prediction to read.

        Returns:
            The prediction's status and, once processing has completed, one result per
            detection target with its score from 0 to 100. `results` is empty while the
            prediction is still processing.
        """
        client = handle.require()
        try:
            detail = await client.predictions.get(prediction_id)
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_prediction_summary(detail)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def list_predictions(
        space_id: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20,
        skip: int = 0,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> ListPage:
        """
        List recent predictions, newest first.

        Args:
            space_id: Restrict to one space.
            statuses: Restrict to certain statuses. Valid values are
                `pending_upload`, `processing`, `completed`, `failed`, `canceled`.
            start_date: Only predictions created on or after this ISO 8601 date.
            end_date: Only predictions created on or before this ISO 8601 date.
            limit: Page size, from 1 to 100.
            skip: How many records to skip, for paging.

        Returns:
            A page of prediction records without their results. Call get_prediction for
            the scores of any one of them.
        """
        client = handle.require()
        size = clamp_limit(limit)
        try:
            page = await client.predictions.list(
                space_id=space_id,
                statuses=statuses,
                start_date=start_date,
                end_date=end_date,
                skip=skip,
                limit=size,
            )
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_page(page, skip=skip)
