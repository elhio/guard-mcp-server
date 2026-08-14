"""
Server-side configuration for the Guard MCP server.

Everything here is specific to *serving* Guard over MCP: which transport to bind,
which directories media may be read from, and how hard callers may hammer the
billable tools. It deliberately does not duplicate the client's own configuration.
`GUARD_API_KEY`, `GUARD_SPACE_ID`, `GUARD_ENGINE` and friends are read by
`guard_client` itself, which already implements the argument, environment, `.env`
file, default precedence chain. Duplicating those names here would create two
sources of truth that drift apart.

Examples:
    ```python
    from guard_mcp.settings import get_settings

    settings = get_settings()
    print(settings.transport, settings.media_roots)
    ```
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, List, Literal, Optional, Tuple

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["GuardMCPSettings", "get_settings", "reset_settings"]

#: Type alias for the supported server listening protocols.
Transport = Literal["stdio", "http"]


class GuardMCPSettings(BaseSettings):
    """
    Settings for the MCP server process, read from `GUARD_MCP_*` environment variables.

    Attributes:
        transport: How the server listens. `stdio` for a locally spawned subprocess,
            `http` for a networked deployment.
        host: Bind address for the HTTP transport.
        port: Bind port for the HTTP transport.
        log_level: Level for the server's own logger. Logs go to stderr so they never
            corrupt the stdio protocol stream.
        media_roots: Directories media may be read from. Empty means "the working
            directory of the server process".
        allow_any_path: Disables the `media_roots` check entirely. This hands any
            agent that can reach the server the ability to submit any readable file
            on the machine, so it is off by default.
        max_media_bytes: Largest file the server will accept, checked before the
            bytes are read.
        default_poll_timeout: Seconds `analyze_media` waits for cloud processing.
        max_poll_timeout: Ceiling a caller may request for that wait.
        max_requests_per_second: Global token-bucket rate for every MCP message.
        burst_capacity: How many requests may arrive at once before the global limit
            applies.
        activity_requests_per_minute: Stricter budget for the tools that create
            billable activities.
        include_payloads_in_logs: Logs tool arguments and results. Useful when
            debugging an agent, noisy otherwise.
        max_payload_log_length: Truncation point for those logged payloads.
        mask_error_details: Replaces unexpected exception text with a generic
            message. Errors this server raises deliberately are always shown.
        enable_tasks: Registers the FastMCP background task extension, which is what
            lets `analyze_media` return a handle instead of blocking on a poll.
            Turning it off makes that tool run synchronously. The extension starts a
            Docket worker, so it is also the switch to reach for when embedding this
            server inside another process that manages its own event loop.
        docket_url: Where background task state lives. `memory://` keeps it inside this
            process; point it at Redis for an HTTP deployment with several workers.
        docket_name: The queue name. Servers and workers sharing a name and a URL share
            a queue.
        docket_concurrency: How many tasks one worker runs at once.
    """

    model_config = SettingsConfigDict(
        env_prefix="GUARD_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # NoDecode keeps pydantic-settings from trying to read the environment value as
    # JSON. A list of directories is naturally written the way PATH is written, and
    # nobody types a JSON array into an MCP client's env block
    media_roots: Annotated[List[Path], NoDecode] = Field(default_factory=list)
    allow_any_path: bool = False
    max_media_bytes: int = 100 * 1024 * 1024

    default_poll_timeout: float = 90.0
    max_poll_timeout: float = 600.0

    max_requests_per_second: float = 10.0
    burst_capacity: int = 20
    activity_requests_per_minute: float = 30.0

    include_payloads_in_logs: bool = False
    max_payload_log_length: int = 1000
    mask_error_details: bool = True
    enable_tasks: bool = True

    # Left unset these stay None, and the tasks extension falls back to its own
    # FASTMCP_DOCKET_* variables. Setting one here wins over the FASTMCP_ name
    docket_url: Optional[str] = None
    docket_name: Optional[str] = None
    docket_concurrency: Optional[int] = None

    @field_validator("media_roots", mode="before")
    @classmethod
    def _split_roots(cls, value: object) -> object:
        """
        Accept an os.pathsep separated string as well as a list.

        Environment variables can only carry a string, and a caller configuring several
        directories should not have to write JSON to do it.

        Args:
            value: The raw value from the environment or an explicit argument.

        Returns:
            A list of path strings when the input was a delimited string, otherwise the
            value unchanged for pydantic to handle.
        """
        if isinstance(value, str):
            return [part for part in value.split(os.pathsep) if part.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        """
        Normalize the level name so `debug` and `DEBUG` behave identically.

        Args:
            value: The configured level name.

        Returns:
            The level name in upper case.
        """
        return value.upper()

    def resolved_media_roots(self) -> Tuple[Path, ...]:
        """
        The directories media may be read from, as absolute resolved paths.

        Returns:
            The configured roots, or a single entry for the process working directory
            when none were configured. Symlinks are resolved so the containment check
            in `guard_mcp.media` compares like with like.
        """
        roots = self.media_roots or [Path.cwd()]
        return tuple(Path(root).expanduser().resolve() for root in roots)


#: The cached settings instance for the life of the process.
_settings: Optional[GuardMCPSettings] = None


def get_settings() -> GuardMCPSettings:
    """
    Build the settings once and reuse them for the life of the process.

    Returns:
        The active `GuardMCPSettings` instance.

    Note:
        Tests that manipulate the environment must call `reset_settings()` afterwards,
        otherwise the first test to read settings fixes them for the whole session.
    """
    global _settings
    if _settings is None:
        _settings = GuardMCPSettings()
    return _settings


def reset_settings(settings: Optional[GuardMCPSettings] = None) -> None:
    """
    Drop the cached settings, optionally installing a replacement.

    Args:
        settings: An instance to serve from now on. Omit it to rebuild from the
            environment on the next `get_settings()` call.
    """
    global _settings
    _settings = settings
