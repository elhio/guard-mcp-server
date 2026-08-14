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
