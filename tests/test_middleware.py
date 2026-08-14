"""
Tests for the middleware stack.

The rate limits are the part worth testing: they are the only thing standing between a
looping agent and a real bill.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.client import Client

from conftest import SPACES_URL, mock_lifecycle, page_response, space_response
from guard_mcp.middleware import (
    ActivityRateLimitMiddleware,
    GuardErrorMiddleware,
    build_middleware,
)
from guard_mcp.server import create_server
from guard_mcp.settings import GuardMCPSettings


def test_the_stack_ends_with_guard_translation(settings):
    """Verify that the Guard translator sits innermost to see original exceptions."""
    stack = build_middleware(settings)

    assert isinstance(stack[-1], GuardErrorMiddleware)
    assert any(isinstance(item, ActivityRateLimitMiddleware) for item in stack)


async def test_deliberate_tool_errors_are_not_relabelled(cloud_env, tmp_path, png):
    """
    A refused media path must reach the agent as written, not as an internal error.

    FastMCP's stock error handler transforms every exception it sees and has no case
    for `ToolError`, so it used to prefix these with "Internal error:" and send them
    with the protocol's -32603 code. An agent told a correctable mistake is an internal
    failure has no reason to correct it.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    settings = GuardMCPSettings(
        media_roots=[allowed], enable_tasks=False, mask_error_details=True
    )
    server = create_server(settings)

    async with Client(server) as session:
        with pytest.raises(Exception) as caught:
            await session.call_tool("analyze_media", {"path": str(png)})

    message = str(caught.value)
    assert "GUARD_MCP_MEDIA_ROOTS" in message
    assert "Internal error" not in message


async def test_the_configuration_error_survives_the_stack(tmp_path, monkeypatch):
    """The missing-key message is the one an agent needs verbatim to be actionable."""
    monkeypatch.delenv("GUARD_API_KEY", raising=False)
    server = create_server(
        GuardMCPSettings(
            media_roots=[tmp_path], enable_tasks=False, mask_error_details=True
        )
    )

    async with Client(server) as session:
        with pytest.raises(Exception) as caught:
            await session.call_tool("list_spaces", {})

    message = str(caught.value)
    assert "GUARD_API_KEY" in message
    assert "Internal error" not in message


async def test_the_billable_budget_stops_a_runaway_agent(cloud_env, tmp_path, png):
    """Verify that the billable budget rate-limits runaway agents with a wait time."""
    settings = GuardMCPSettings(
        media_roots=[tmp_path],
        enable_tasks=False,
        mask_error_details=False,
        activity_requests_per_minute=1.0,
    )
    server = create_server(settings)

    with respx.mock:
        mock_lifecycle()
        respx.get(SPACES_URL).mock(
            return_value=httpx.Response(200, json=page_response([space_response()]))
        )
        async with Client(server) as session:
            first = await session.call_tool("analyze_media", {"path": str(png)})
            assert first.structured_content["max_score"] == 87

            with pytest.raises(Exception, match="budget is spent"):
                await session.call_tool("analyze_media", {"path": str(png)})

            # A cheap read-only tool is unaffected by the moderation budget.
            result = await session.call_tool("list_spaces", {})
            assert result.structured_content["count"] == 1


async def test_the_global_limit_covers_every_tool(cloud_env, tmp_path):
    """Verify that the global rate limit restricts excessive calls to any tool."""
    settings = GuardMCPSettings(
        media_roots=[tmp_path],
        enable_tasks=False,
        mask_error_details=False,
        max_requests_per_second=0.001,
        burst_capacity=1,
    )
    server = create_server(settings)

    with respx.mock:
        respx.get(SPACES_URL).mock(
            return_value=httpx.Response(200, json=page_response([space_response()]))
        )
        async with Client(server) as session:
            with pytest.raises(Exception, match="[Rr]ate limit"):
                for _ in range(10):
                    await session.call_tool("list_spaces", {})
