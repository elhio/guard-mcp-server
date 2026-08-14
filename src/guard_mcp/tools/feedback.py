"""
Reporting on a result and handing it to someone else.

Feedback closes the loop when a human disagrees with a score, which is the signal the
platform learns from. A share turns one result into a link that can be opened without
an API key, so a moderator can look at the media themselves.

Both act on a specific `(activity_id, task_id)` pair, because a single activity carries
one result per detection task and the two operations are only meaningful about one of
them at a time. The ids come from `analyze_media` or `get_activity`.

Examples:
    ```python
    await submit_feedback(
        activity_id,
        task_id,
        is_positive=False,
        description="clearly a painting, not a photo",
    )
    ```
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastmcp import FastMCP
from fastmcp.dependencies import Shared
from guard_client import GuardError

from ..client import GuardClientHandle, guard_client
from ..errors import to_tool_error
from ..utils import to_dict

__all__ = ["register"]


def register(mcp: FastMCP) -> None:
    """
    Attach the feedback and sharing tools to a server.

    Args:
        mcp: The server to register on.
    """

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
    async def submit_feedback(
        activity_id: str,
        task_id: str,
        is_positive: bool,
        description: Optional[str] = None,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> Dict[str, Any]:
        """
        Tell the platform whether one detection result was right.

        Args:
            activity_id: The activity the result belongs to.
            task_id: Which detection task's result is being judged. Take it from the
                `task_id` of a finding.
            is_positive: True when the result was correct, False when it was wrong.
            description: Up to 255 characters explaining the judgment. Say what the
                media actually shows, not what the score should have been.

        Returns:
            The stored reaction.

        Notes:
            Only one reaction may exist per activity and task. Submitting a second one
            reports a conflict rather than replacing the first.
        """
        client = handle.require()
        try:
            reaction = await client.reactions.create(
                activity_id=activity_id,
                task_id=task_id,
                is_positive=is_positive,
                description=description,
            )
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_dict(reaction)

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
    async def share_result(
        activity_id: str,
        task_id: str,
        expires_in: Optional[int] = None,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> Dict[str, Any]:
        """
        Create a link to one detection result that anyone can open.

        Args:
            activity_id: The activity to share.
            task_id: Which detection task's result to show.
            expires_in: Days until the link stops working, from 1 to 7. Defaults to the
                platform default.

        Returns:
            The share, including the URL to hand to a person and when it expires.

        Note:
            The link shows the analyzed media to whoever holds it. Do not post one
            somewhere public without checking that is intended.
        """
        client = handle.require()
        try:
            share = await client.shares.create(
                activity_id=activity_id, task_id=task_id, expires_in=expires_in
            )
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        return to_dict(share)
