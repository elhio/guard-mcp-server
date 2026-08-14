"""
Tests for the tools, driven over the in-memory MCP transport with a mocked API.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from conftest import (
    ACTIVITIES_URL,
    ACTIVITY_ID,
    PREDICTORS_URL,
    REACTIONS_URL,
    SHARES_URL,
    SPACES_URL,
    TASK_ID,
    TASKS_URL,
    create_response,
    detail_response,
    mock_lifecycle,
    page_response,
    predictor_response,
    reaction_response,
    result_item,
    share_response,
    space_detail_response,
    space_response,
    task_response,
)


@respx.mock
async def test_analyze_media_runs_the_whole_lifecycle(client, png):
    """Verify that analyze_media runs the complete lifecycle of upload and polling."""
    routes = mock_lifecycle()

    async with client as session:
        result = await session.call_tool("analyze_media", {"path": str(png)})

    for name, route in routes.items():
        assert route.called, f"{name} was never called"

    data = result.structured_content
    assert data["engine"] == "cloud"
    assert data["activity_id"] == str(ACTIVITY_ID)
    assert data["max_score"] == 87
    assert data["results"][0]["task_id"] == str(TASK_ID)
    assert data["results"][0]["score"] == 87


@respx.mock
async def test_the_result_carries_no_verdict_of_its_own(client, png):
    """
    Verify that results report raw scores without applying classification verdicts.
    """
    mock_lifecycle(results=[result_item(score=40)])

    async with client as session:
        result = await session.call_tool("analyze_media", {"path": str(png)})

    data = result.structured_content
    assert set(data) == {"engine", "activity_id", "max_score", "results"}
    assert set(data["results"][0]) <= {
        "task_id",
        "score",
        "label",
        "description",
        "detected",
        "matches",
    }
    assert data["max_score"] == 40


@respx.mock
async def test_results_drop_presigned_media_urls(client, png):
    """Verify that presigned media URLs are dropped from the final analysis result."""
    mock_lifecycle()

    async with client as session:
        result = await session.call_tool("analyze_media", {"path": str(png)})

    assert "media_url" not in str(result.structured_content)
    assert "media_key" not in str(result.structured_content)


@respx.mock
async def test_estimate_tokens_reads_the_space_multiplier(client, png):
    """
    Verify that estimate_tokens fetches and applies the space predictor multiplier.
    """
    respx.get(f"{SPACES_URL}{space_response()['id']}").mock(
        return_value=httpx.Response(200, json=space_detail_response())
    )

    async with client as session:
        result = await session.call_tool("estimate_tokens", {"path": str(png)})

    data = result.structured_content
    assert data["multiplier"] == 3
    assert data["frames"] == 1
    assert data["tokens"] == data["frames"] * data["tier_cost"] * data["multiplier"]


@respx.mock
async def test_estimate_with_an_explicit_multiplier_makes_no_request(client, png):
    """Verify that providing an explicit multiplier skips the space lookup request."""
    route = respx.get(f"{SPACES_URL}{space_response()['id']}").mock(
        return_value=httpx.Response(200, json=space_detail_response())
    )

    async with client as session:
        await session.call_tool("estimate_tokens", {"path": str(png), "multiplier": 5})

    assert not route.called


@respx.mock
async def test_get_activity_returns_the_stored_results(client):
    """Verify that get_activity returns the correct status and stored task results."""
    respx.get(f"{ACTIVITIES_URL}{ACTIVITY_ID}").mock(
        return_value=httpx.Response(200, json=detail_response())
    )

    async with client as session:
        result = await session.call_tool(
            "get_activity", {"activity_id": str(ACTIVITY_ID)}
        )

    data = result.structured_content
    assert data["id"] == str(ACTIVITY_ID)
    assert data["status"] == "completed"
    assert data["payed_tokens"] == 3
    assert data["results"][0]["score"] == 87
    assert data["results"][0]["task_id"] == str(TASK_ID)


@respx.mock
async def test_get_activity_has_no_results_while_processing(client):
    """Verify that an activity still in the processing state returns empty results."""
    respx.get(f"{ACTIVITIES_URL}{ACTIVITY_ID}").mock(
        return_value=httpx.Response(
            200, json=detail_response("processing", result_payload=None)
        )
    )

    async with client as session:
        result = await session.call_tool(
            "get_activity", {"activity_id": str(ACTIVITY_ID)}
        )

    assert result.structured_content["status"] == "processing"
    assert result.structured_content["results"] == []


@respx.mock
async def test_list_activities_reports_the_next_page(client):
    """Verify that list_activities correctly calculates pagination and next_skip."""
    items = [
        create_response(id=f"0000000{n}-0000-0000-0000-000000000000") for n in range(2)
    ]
    for item in items:
        item.pop("upload_data")
    respx.get(ACTIVITIES_URL).mock(
        return_value=httpx.Response(200, json=page_response(items, count=10))
    )

    async with client as session:
        result = await session.call_tool("list_activities", {"limit": 2})

    data = result.structured_content
    assert data["count"] == 10
    assert data["has_more"] is True
    assert data["next_skip"] == 2
    assert len(data["items"]) == 2


@respx.mock
async def test_list_activities_caps_the_page_size(client):
    """Verify that list_activities enforces the maximum API page size limit of 100."""
    route = respx.get(ACTIVITIES_URL).mock(
        return_value=httpx.Response(200, json=page_response([]))
    )

    async with client as session:
        await session.call_tool("list_activities", {"limit": 5000})

    assert route.calls.last.request.url.params["limit"] == "100"


@respx.mock
async def test_list_spaces(client):
    """Verify that list_spaces returns a parsed page of available space records."""
    respx.get(SPACES_URL).mock(
        return_value=httpx.Response(200, json=page_response([space_response()]))
    )

    async with client as session:
        result = await session.call_tool("list_spaces", {})

    assert result.structured_content["items"][0]["name"] == "Test Space"


@respx.mock
async def test_get_space_exposes_tasks_and_thresholds(client):
    """Verify that get_space exposes detailed enabled tasks and score thresholds."""
    space_id = space_response()["id"]
    respx.get(f"{SPACES_URL}{space_id}").mock(
        return_value=httpx.Response(200, json=space_detail_response())
    )

    async with client as session:
        result = await session.call_tool("get_space", {"space_id": space_id})

    data = result.structured_content
    assert data["predictor_multiplier"] == 3
    assert data["enabled_tasks"][0]["name"] == "Deepfake"
    assert data["task_thresholds"][0]["hide_threshold"] == 80


@respx.mock
async def test_list_detection_tasks(client):
    """Verify that list_detection_tasks returns the available detection task catalog."""
    respx.get(TASKS_URL).mock(
        return_value=httpx.Response(200, json=page_response([task_response()]))
    )

    async with client as session:
        result = await session.call_tool("list_detection_tasks", {})

    assert result.structured_content["items"][0]["id"] == str(TASK_ID)


@respx.mock
async def test_list_predictors(client):
    """Verify that list_predictors returns the catalog of available ML predictors."""
    respx.get(PREDICTORS_URL).mock(
        return_value=httpx.Response(200, json=page_response([predictor_response()]))
    )

    async with client as session:
        result = await session.call_tool("list_predictors", {})

    assert result.structured_content["items"][0]["token_multiplier"] == 3


@respx.mock
async def test_submit_feedback(client):
    """Verify that submit_feedback successfully records a user reaction to a result."""
    route = respx.post(REACTIONS_URL).mock(
        return_value=httpx.Response(200, json=reaction_response())
    )

    async with client as session:
        result = await session.call_tool(
            "submit_feedback",
            {
                "activity_id": str(ACTIVITY_ID),
                "task_id": str(TASK_ID),
                "is_positive": False,
                "description": "a painting, not a photo",
            },
        )

    assert route.called
    assert result.structured_content["activity_id"] == str(ACTIVITY_ID)


@respx.mock
async def test_share_result(client):
    """Verify that share_result successfully generates a public shareable link."""
    respx.post(SHARES_URL).mock(return_value=httpx.Response(200, json=share_response()))

    async with client as session:
        result = await session.call_tool(
            "share_result",
            {"activity_id": str(ACTIVITY_ID), "task_id": str(TASK_ID)},
        )

    assert result.structured_content["share_url"].startswith("https://")


@respx.mock
async def test_spaces_resource_lists_every_space(client):
    """
    Verify that the guard://spaces resource successfully lists all available spaces.
    """
    respx.get(SPACES_URL).mock(
        return_value=httpx.Response(200, json=page_response([space_response()]))
    )

    async with client as session:
        contents = await session.read_resource("guard://spaces")

    assert "Test Space" in contents[0].text


@respx.mock
async def test_a_failed_activity_explains_itself(client, png):
    """
    Verify that a failed analysis activity raises an exception explaining the failure.
    """
    mock_lifecycle(status="failed")

    async with client as session:
        with pytest.raises(Exception, match="failed"):
            await session.call_tool("analyze_media", {"path": str(png)})
