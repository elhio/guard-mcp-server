"""
The tools that actually analyze media.

The `analyze_media` tool is the reason this server exists and the only tool declared as
a background task. A cloud analysis creates an activity, uploads the bytes, and then
polls until a GPU somewhere has finished with it, which for a video can take a minute
or more. Run synchronously that blocks the agent's turn; run as a task the agent gets
a handle immediately and collects the result when it is ready.

The lifecycle itself is not reimplemented here. `AsyncGuardClient.analyze` already does
create, upload, confirm, poll and fetch, and it is the code path the client's own test
suite covers.

Examples:
    ```python
    result = await analyze_media("/srv/uploads/photo.jpg")
    print(result.max_score, [item.label for item in result.results])
    ```
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal, Optional

from fastmcp import FastMCP
from fastmcp.dependencies import Progress, Shared
from fastmcp.utilities.tasks import TaskConfig
from guard_client import GuardError, TokenEstimate

from ..client import GuardClientHandle, guard_client
from ..errors import to_tool_error
from ..media import describe_media, resolve_media_path
from ..schemas import AnalysisResult
from ..settings import GuardMCPSettings, get_settings

__all__ = ["register"]

#: The time in seconds to wait between status checks when polling the API.
_POLL_INTERVAL = 2.0


def register(mcp: FastMCP, settings: Optional[GuardMCPSettings] = None) -> None:
    """
    Attach the moderation tools to a server.

    Args:
        mcp: The server to register on.
        settings: Decides whether `analyze_media` is declared as a background task.
            FastMCP refuses to serve a task-declared tool unless the tasks extension
            is registered, so the two decisions have to agree.
    """
    settings = settings or get_settings()
    task_config = (
        TaskConfig(mode="optional", poll_interval=timedelta(seconds=2))
        if settings.enable_tasks
        else None
    )

    @mcp.tool(
        task=task_config,
        annotations={"readOnlyHint": False, "openWorldHint": True},
    )
    async def analyze_media(
        path: str,
        space_id: Optional[str] = None,
        engine: Optional[Literal["cloud", "local"]] = None,
        timeout: Optional[float] = None,
        handle: GuardClientHandle = Shared(guard_client),
        progress: Progress = Progress(),
    ) -> AnalysisResult:
        """
        Analyze one image or video for AI-generated, violent, or explicit content.

        Args:
            path: Path to a media file on the machine running this server. Must sit
                inside a directory this server is configured to read.
            space_id: Which space to analyze in. Defaults to the server's configured
                space. Use list_spaces to see the options.
            engine: `cloud` for the full model, `local` for the lighter on-device one.
                Defaults to the server's configured engine.
            timeout: Seconds to wait for processing. Defaults to the server setting.

        Returns:
            One result per detection task, each with a score from 0 to 100 where higher
            means more strongly detected, plus the highest of those scores and the id of
            the activity that produced them.

        Notes:
            This tool can run as a background task, and the calling client decides per
            call. Ask for one and the call returns a task handle immediately, to be
            polled for the `AnalysisResult`; ask for nothing and the result comes back
            directly, which for a video may take a minute or more.

            Task ids differ between engines. The on-device engine derives its ids from
            the task label, so they will not match the ids a space reports.
        """
        client = handle.require()

        await progress.set_total(3)
        await progress.set_message("checking media")
        resolved = resolve_media_path(path, settings=settings)
        describe_media(resolved)
        await progress.increment()

        wait_for = min(
            timeout if timeout is not None else settings.default_poll_timeout,
            settings.max_poll_timeout,
        )

        await progress.set_message("analyzing")
        try:
            detection = await client.analyze(
                str(resolved),
                space_id=space_id,
                engine=engine,
                poll_interval=_POLL_INTERVAL,
                timeout=wait_for,
            )
        except GuardError as exc:
            raise to_tool_error(exc) from exc
        await progress.increment()

        await progress.set_message("done")
        await progress.increment()
        return AnalysisResult.from_detection(detection)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def estimate_tokens(
        path: str,
        space_id: Optional[str] = None,
        multiplier: Optional[int] = None,
        handle: GuardClientHandle = Shared(guard_client),
    ) -> TokenEstimate:
        """
        Project how many tokens analyzing a file will use.

        Args:
            path: Path to the media file to measure.
            space_id: Whose predictor multiplier to use. Defaults to the server's
                configured space.
            multiplier: Supply the multiplier directly to skip the space lookup and
                make this call entirely offline.

        Returns:
            The projected token total and the breakdown behind it: frames, resolution
            tier, per-frame cost, and multiplier.

        Notes:
            This is an estimate. The API reserves a minimum up front and charges the
            real amount once processing finishes.
        """
        client = handle.require()
        resolved = resolve_media_path(path, settings=settings)
        describe_media(resolved)

        try:
            return await client.estimate_tokens(
                str(resolved), space_id=space_id, multiplier=multiplier
            )
        except GuardError as exc:
            raise to_tool_error(exc) from exc
