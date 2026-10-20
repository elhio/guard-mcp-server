"""
A task-enabled server driven end to end, for `test_tasks.py` to run as a subprocess.

This cannot live inside the pytest process: the Docket worker the tasks extension
starts keeps a heartbeat on the event loop after the MCP session ends, which leaves
pytest-asyncio's runner with work it will wait on forever. A subprocess gets the same
coverage and exits cleanly.

Prints one line of JSON with the moderation result, or exits non-zero.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import tempfile
import zlib
import zoneinfo  # noqa: F401  (imported early; pydocket touches tzdata on some hosts)
from pathlib import Path


def png_bytes() -> bytes:
    """A real 1x1 PNG."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


class FakeEngine:
    """Stands in for the on-device engine so the run needs no network and no model."""

    def analyze(self, data, media_type):
        return [
            {"label": "AI-Generated", "score": 0.9, "detected": True, "matches": []},
            {"label": "Violence", "score": 0.1, "detected": False, "matches": []},
            {"label": "Explicit", "score": 0.05, "detected": False, "matches": []},
        ]


async def main() -> int:
    """
    Run one moderation through a task-enabled server.

    Returns:
        A process exit code.
    """
    workdir = Path(tempfile.mkdtemp())
    os.chdir(workdir)
    for key in [k for k in os.environ if k.startswith(("GUARD_", "FASTMCP_"))]:
        del os.environ[key]
    os.environ["GUARD_ENGINE"] = "local"
    os.environ["FASTMCP_DOCKET_URL"] = "memory://"

    from fastmcp.client import Client
    from guard_client.local import LocalRunner

    from guard_mcp.server import create_server
    from guard_mcp.settings import GuardMCPSettings, reset_settings

    LocalRunner._ensure_engine = lambda self: FakeEngine()

    media = workdir / "photo.png"
    media.write_bytes(png_bytes())

    settings = GuardMCPSettings(
        media_roots=[workdir], enable_tasks=True, mask_error_details=False
    )
    reset_settings(settings)

    server = create_server(settings)
    tool = await server.get_tool("analyze_media")
    plain = await server.get_tool("get_prediction")

    async with Client(server) as session:
        result = await session.call_tool("analyze_media", {"path": str(media)})

    print(
        json.dumps(
            {
                "task_mode": getattr(tool.task_config, "mode", None),
                "plain_tool_mode": getattr(plain.task_config, "mode", None),
                "result": result.structured_content,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
