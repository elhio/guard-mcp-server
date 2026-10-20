"""
Tests for the client-exception to tool-error translation.

An agent only ever sees the message, so each test asserts on the part of it that tells
the agent what to do next, not on the wording around it.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from guard_client import (
    GuardAPIError,
    GuardAuthError,
    GuardConflictError,
    GuardConnectionError,
    GuardError,
    GuardLocalModelError,
    GuardMediaDecodeError,
    GuardNotFoundError,
    GuardPaymentRequiredError,
    GuardRateLimitError,
    GuardServerError,
    GuardTimeoutError,
    GuardUploadError,
    GuardValidationError,
    LocalEngineNotInstalledError,
    PredictionFailedError,
    UnsupportedMediaTypeError,
)

from conftest import PREDICTION_ID, PREDICTIONS_URL, SPACES_URL, create_response
from guard_mcp.errors import to_tool_error


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (GuardAuthError("nope", status_code=401), "GUARD_API_KEY"),
        (GuardPaymentRequiredError("no plan", status_code=402), "subscription"),
        (GuardNotFoundError("gone", status_code=404), "Check the id"),
        (GuardConflictError("exists", status_code=409), "already"),
        (
            GuardValidationError(
                "bad", status_code=422, detail=[{"loc": ["body", "x"], "msg": "req"}]
            ),
            "loc",
        ),
        (GuardServerError("boom", status_code=503), "transient"),
        (GuardRateLimitError("slow", status_code=429, retry_after=12), "12 seconds"),
        (GuardRateLimitError("slow", status_code=429), "Retry shortly"),
        (GuardConnectionError("unreachable"), "GUARD_BASE_URL"),
        (GuardUploadError("expired"), "submit the media again"),
        (GuardAPIError("teapot", status_code=418), "418"),
        (GuardTimeoutError("too slow", prediction_id=PREDICTION_ID), "get_prediction"),
        (PredictionFailedError("bad", status="canceled"), "canceled"),
        (LocalEngineNotInstalledError("absent"), "guard-mcp-server[local]"),
        (GuardLocalModelError("no model"), "GUARD_LOCAL_MODEL_PATH"),
        (GuardMediaDecodeError("garbage"), "could not decode"),
        (UnsupportedMediaTypeError("application/pdf"), "image/png"),
        (GuardError("something local"), "something local"),
    ],
)
def test_every_client_error_becomes_an_actionable_message(exception, expected):
    assert expected in str(to_tool_error(exception))


def test_the_request_id_is_quoted_when_the_server_sent_one():
    exception = GuardAuthError("nope", status_code=401, request_id="req-42")

    assert "req-42" in str(to_tool_error(exception))


def test_the_local_engine_hint_names_its_license():
    assert "AGPL" in str(to_tool_error(LocalEngineNotInstalledError("absent")))


@respx.mock
async def test_an_api_error_reaches_the_agent_through_a_tool(client):
    respx.get(SPACES_URL).mock(
        return_value=httpx.Response(401, json={"detail": "Invalid API key"})
    )

    async with client as session:
        with pytest.raises(Exception, match="GUARD_API_KEY"):
            await session.call_tool("list_spaces", {})


@respx.mock
async def test_a_timeout_names_the_prediction_to_come_back_to(client, png):
    respx.post(PREDICTIONS_URL).mock(
        return_value=httpx.Response(200, json=create_response())
    )
    respx.post("https://s3.test.invalid/bucket").mock(return_value=httpx.Response(204))
    respx.post(f"{PREDICTIONS_URL}/{PREDICTION_ID}/confirm").mock(
        return_value=httpx.Response(200, json=create_response(status="processing"))
    )
    respx.get(f"{PREDICTIONS_URL}/{PREDICTION_ID}/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": str(PREDICTION_ID),
                "status": "processing",
                "user_id": None,
                "account_id": None,
                "guest_id": None,
            },
        )
    )

    async with client as session:
        with pytest.raises(Exception, match=str(PREDICTION_ID)):
            await session.call_tool(
                "analyze_media", {"path": str(png), "timeout": 0.01}
            )
