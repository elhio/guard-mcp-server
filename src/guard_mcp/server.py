"""
The Guard MCP server: construction, wiring, and the command line entry point.

The `create_server` function is the single place that assembles everything. Tests build
their own instance from it and drive it over an in-memory transport; the console script
builds one and runs it over stdio or HTTP.

The instructions handed to the server matter more than they look. They are the only
thing a model reads before deciding how to use these tools, so they state the three
rules it cannot guess: media is a local path, scores run 0 to 100, and a score is a
measurement rather than a verdict.

Examples:
    ```bash
    guard-mcp                                # stdio, for a locally spawned server
    guard-mcp --transport http --port 9000   # networked
    ```
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from fastmcp import FastMCP

from . import resources
from .middleware import build_middleware
from .settings import GuardMCPSettings, get_settings
from .tools import register_all

__all__ = ["create_server", "main"]

INSTRUCTIONS = """
Visual content analysis through the Guard API. Use these tools to measure how strongly
an image or video matches AI-generated, violent, or sexually explicit content before
publishing, storing, or acting on it.

Start with analyze_media. It takes the path of a media file on the machine running this
server, not a URL and not inline data, and the file must sit inside a directory this
server is configured to read. Read the guard://config resource to see which directories
those are.

It returns one result per detection task, each with a score from 0 to 100 where higher
means more strongly detected, plus the highest of those scores. A score is a
measurement, not a decision: these tools report what the models found and do not
classify media as acceptable or unacceptable.

A cloud analysis can take a minute for a video. analyze_media can run as a background
task, so a client that asks for one gets a handle straight away and collects the result
when it is ready, rather than waiting. If the wait times out either way, the error names
an activity id: call get_activity with it later to collect the result.

Use estimate_tokens first when cost matters. Use submit_feedback when a human has
established that a score was wrong.
"""


def create_server(settings: Optional[GuardMCPSettings] = None) -> FastMCP:
    """
    Build a fully wired server instance.

    Args:
        settings: Overrides the process settings. Mainly for tests.

    Returns:
        A `FastMCP` server with every tool, resource, and middleware attached, and the
        background task extension registered when it is installed.
    """
    settings = settings or get_settings()

    mcp: FastMCP = FastMCP(
        name="guard",
        instructions=INSTRUCTIONS.strip(),
        version=_version(),
        middleware=build_middleware(settings),
        mask_error_details=settings.mask_error_details,
    )

    if settings.enable_tasks:
        _register_tasks_extension(mcp, settings)
    register_all(mcp, settings)
    resources.register(mcp)
    return mcp


def _register_tasks_extension(mcp: FastMCP, settings: GuardMCPSettings) -> None:
    """
    Enable background task execution, when the tasks package is installed.

    Args:
        mcp: The server to register the extension on.
        settings: Supplies the task backend, read from `GUARD_MCP_DOCKET_*`.

    Notes:
        Tools declared with `task=TaskConfig(mode="optional")` still run, synchronously,
        when the extension is absent. Failing to start over a missing optional
        extension would be a worse trade than running the slow path.

        Each backend setting is passed only when it was set. The extension drops `None`
        overrides, so an unset one falls through to its own `FASTMCP_DOCKET_*` variable
        and then to the FastMCP default, which keeps both spellings working.
    """
    try:
        from fastmcp_tasks import TasksExtension
    except ImportError:  # pragma: no cover
        logging.getLogger("guard_mcp").warning(
            "fastmcp-tasks is not installed; analyze_media will run synchronously."
        )
        return
    mcp.add_extension(
        TasksExtension(
            url=settings.docket_url,
            name=settings.docket_name,
            concurrency=settings.docket_concurrency,
        )
    )


def _version() -> str:
    """
    Get the installed version of this package.

    Returns:
        The distribution version, or `0.0.0+unknown` when the package is not installed.
    """
    from . import __version__

    return __version__


def _configure_logging(settings: GuardMCPSettings) -> None:
    """
    Send this server's logs to stderr.

    Args:
        settings: Supplies the log level.

    Notes:
        stdout carries the MCP protocol on the stdio transport. A single stray print or
        log line there corrupts the stream and the client disconnects.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse the command line, defaulting to the configured settings.

    Args:
        argv: Arguments to parse. Defaults to `sys.argv`.

    Returns:
        The parsed arguments.
    """
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="MCP server for Guard visual content moderation.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=settings.transport,
        help="How to listen. Defaults to GUARD_MCP_TRANSPORT, or stdio.",
    )
    parser.add_argument(
        "--host", default=settings.host, help="Bind address for the http transport."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help="Bind port for the http transport.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """
    Run the server from the command line.

    Args:
        argv: Arguments to parse. Defaults to `sys.argv`.
    """
    settings = get_settings()
    _configure_logging(settings)
    args = _parse_args(argv)

    server = create_server(settings)
    if args.transport == "http":
        server.run(transport="http", host=args.host, port=args.port)
    else:
        server.run()


if __name__ == "__main__":
    main()
