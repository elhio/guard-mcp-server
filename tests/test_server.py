"""
Tests for server construction, the tool surface, and the config resource.
"""

from __future__ import annotations

import json
import os

import pytest
from fastmcp.client import Client

from conftest import API_KEY, png_bytes
from guard_mcp.server import create_server
from guard_mcp.settings import GuardMCPSettings, reset_settings

EXPECTED_TOOLS = {
    "analyze_media",
    "estimate_tokens",
    "get_activity",
    "list_activities",
    "list_spaces",
    "get_space",
    "list_detection_tasks",
    "list_predictors",
    "submit_feedback",
    "share_result",
}


async def test_exposes_the_expected_tools(client):
    """Verify that the server exposes all expected tools and no others."""
    async with client as session:
        tools = await session.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_every_tool_documents_itself(client):
    """Verify that every registered tool includes a description for the agent."""
    async with client as session:
        tools = await session.list_tools()

    for tool in tools:
        assert tool.description, f"{tool.name} has no description"


async def test_injected_dependencies_stay_out_of_the_schema(client):
    """The shared client and progress reporter are not things an agent may pass."""
    async with client as session:
        tools = await session.list_tools()

    for tool in tools:
        properties = set(tool.input_schema.get("properties", {}))
        assert "handle" not in properties
        assert "progress" not in properties


async def test_server_carries_usage_instructions(server):
    """Verify that the server includes usage instructions mentioning paths."""
    assert server.instructions
    assert "path" in server.instructions.lower()


async def test_config_resource_reports_readiness_without_the_key(client):
    """Verify that the config resource redacts the API key while reporting readiness."""
    async with client as session:
        contents = await session.read_resource("guard://config")

    payload = json.loads(contents[0].text)
    assert payload["guard_client"]["ready"] is True
    assert payload["guard_client"]["api_key_present"] is True
    assert API_KEY not in contents[0].text


async def test_missing_credentials_do_not_stop_the_server(settings, monkeypatch):
    """
    Verify missing credentials surface as tool errors rather than startup crashes.

    A client that cannot start the server shows the user nothing beyond "failed", so
    the diagnosis has to travel in a tool result instead.
    """
    monkeypatch.delenv("GUARD_API_KEY", raising=False)
    server = create_server(settings)

    async with Client(server) as session:
        contents = await session.read_resource("guard://config")
        payload = json.loads(contents[0].text)
        assert payload["guard_client"]["ready"] is False

        with pytest.raises(Exception, match="GUARD_API_KEY"):
            await session.call_tool("list_spaces", {})


async def test_local_engine_needs_no_api_key(settings, monkeypatch):
    """
    Verify that the local engine can initialize and report readiness without a key.
    """
    monkeypatch.delenv("GUARD_API_KEY", raising=False)
    monkeypatch.setenv("GUARD_ENGINE", "local")
    server = create_server(settings)

    async with Client(server) as session:
        contents = await session.read_resource("guard://config")

    payload = json.loads(contents[0].text)
    assert payload["guard_client"]["ready"] is True
    assert payload["guard_client"]["engine"] == "local"


async def test_injected_settings_govern_the_media_check(cloud_env, tmp_path):
    """
    Settings handed to `create_server` must reach the tool that reads media.

    `analyze_media` used to call `get_settings()` in its own body, so the settings
    argument silently did not apply to it. Nothing here installs the settings globally,
    which is what makes the difference visible: the process settings would allow the
    working directory, and the injected ones must not.

    `enable_tasks` is off for the reason every test here has it off: the Docket worker
    keeps a heartbeat scheduled past the end of the session and pytest-asyncio waits on
    it forever.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "photo.png"
    outside.write_bytes(png_bytes())

    server = create_server(
        GuardMCPSettings(
            media_roots=[allowed], mask_error_details=False, enable_tasks=False
        )
    )

    async with Client(server) as session:
        with pytest.raises(Exception, match="not allowed"):
            await session.call_tool("analyze_media", {"path": str(outside)})


def test_settings_read_media_roots_from_a_delimited_string(monkeypatch, tmp_path):
    """Verify that `media_roots` correctly parses a delimited string of paths."""
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("GUARD_MCP_MEDIA_ROOTS", f"{tmp_path}{os.pathsep}{other}")
    reset_settings()

    settings = GuardMCPSettings()

    assert settings.resolved_media_roots() == (tmp_path.resolve(), other.resolve())
