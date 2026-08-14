"""
Tests for the background task wiring.

The task path runs in a subprocess. The Docket worker that the tasks extension starts
keeps a heartbeat scheduled on the event loop after the MCP session closes, and
pytest-asyncio waits for that loop to drain, so an in-process test never returns. The
subprocess covers the same ground and exits cleanly; `tests/task_probe.py` is the
script it runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp.client import Client

from guard_mcp.server import create_server
from guard_mcp.settings import GuardMCPSettings

PROBE = Path(__file__).parent / "task_probe.py"


@pytest.mark.slow
def test_a_task_enabled_server_moderates_end_to_end():
    """
    Verify the end-to-end path: extension registered, task declared, result returned.
    """
    completed = subprocess.run(
        [sys.executable, str(PROBE)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["task_mode"] == "optional"
    assert payload["plain_tool_mode"] == "forbidden"
    assert payload["result"]["max_score"] == 90


async def test_disabling_tasks_leaves_the_tool_synchronous(settings):
    """
    Verify that with tasks off, analyze_media is not declared as a task.

    FastMCP refuses to serve a task-declared tool when the extension is missing, so the
    two settings have to move together or the server will not start at all.
    """
    server = create_server(settings)
    tool = await server.get_tool("analyze_media")

    assert settings.enable_tasks is False
    assert tool.task_config.mode == "forbidden"


def _docket_settings(server):
    """The Docket configuration the registered tasks extension resolved."""
    extensions = list(server._extensions.values())
    assert len(extensions) == 1, extensions
    return extensions[0].docket_settings


def test_the_task_backend_reads_our_own_env_names(monkeypatch):
    """Verify GUARD_MCP_DOCKET_* configures the backend, ignoring FASTMCP_ names."""
    monkeypatch.setenv("GUARD_MCP_DOCKET_URL", "redis://example:6379/3")
    monkeypatch.setenv("GUARD_MCP_DOCKET_NAME", "guard-queue")
    monkeypatch.setenv("GUARD_MCP_DOCKET_CONCURRENCY", "4")

    docket = _docket_settings(create_server(GuardMCPSettings()))

    assert docket.url == "redis://example:6379/3"
    assert docket.name == "guard-queue"
    assert docket.concurrency == 4


def test_an_unset_backend_falls_through_to_the_fastmcp_name(monkeypatch):
    """
    Verify both spellings work, and ours wins where both are set.

    Anyone already configuring FASTMCP_DOCKET_* keeps working, because an unset
    GUARD_MCP_ setting is passed as None and the extension drops it.
    """
    monkeypatch.setenv("FASTMCP_DOCKET_URL", "redis://fallback:6379/0")
    monkeypatch.setenv("FASTMCP_DOCKET_NAME", "from-fastmcp")
    monkeypatch.setenv("GUARD_MCP_DOCKET_URL", "redis://ours:6379/1")

    docket = _docket_settings(create_server(GuardMCPSettings()))

    assert docket.url == "redis://ours:6379/1"
    assert docket.name == "from-fastmcp"
    assert docket.concurrency == 10


async def test_the_synchronous_path_still_answers(client, png, monkeypatch):
    """Verify a client that cannot do tasks still gets a result by waiting for it."""
    from guard_client.local import LocalRunner

    monkeypatch.setenv("GUARD_ENGINE", "local")
    monkeypatch.setattr(
        LocalRunner,
        "_ensure_engine",
        lambda self: _StubEngine(),
        raising=True,
    )
    server = create_server(
        GuardMCPSettings(media_roots=[png.parent], enable_tasks=False)
    )

    async with Client(server) as session:
        result = await session.call_tool(
            "analyze_media", {"path": str(png), "engine": "local"}
        )

    assert result.structured_content["engine"] == "local"


class _StubEngine:
    """The smallest engine that produces one clear result."""

    def analyze(self, data, media_type):
        return [{"label": "AI-Generated", "score": 0.1, "detected": False}]
