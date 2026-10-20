"""
Shared fixtures and payload builders for the MCP server test suite.

The suite never touches the network. Guard API calls are intercepted with respx, and
the MCP protocol runs over FastMCP's in-memory transport, so a test exercises the same
server object a real client would talk to without spawning a process.
"""

from __future__ import annotations

import os
import struct
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import pytest

from guard_mcp.settings import GuardMCPSettings, reset_settings

BASE_URL = "https://api.test.invalid"
API_KEY = "test-key"
SPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
PREDICTION_ID = UUID("22222222-2222-2222-2222-222222222222")
TARGET_ID = UUID("33333333-3333-3333-3333-333333333333")
ORG_ID = UUID("44444444-4444-4444-4444-444444444444")
PREDICTOR_ID = UUID("55555555-5555-5555-5555-555555555555")
REACTION_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SHARE_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
UPLOAD_URL = "https://s3.test.invalid/bucket"

PREDICTIONS_URL = f"{BASE_URL}/api/v1/predictions"
SPACES_URL = f"{BASE_URL}/api/v1/spaces"
TARGETS_URL = f"{BASE_URL}/api/v1/targets"
PREDICTORS_URL = f"{BASE_URL}/api/v1/predictors"
REACTIONS_URL = f"{BASE_URL}/api/v1/reactions"
SHARES_URL = f"{BASE_URL}/api/v1/predictions/shares"


def png_bytes() -> bytes:
    """A real 1x1 PNG, so magic-byte sniffing has something valid to work with."""

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


def _now() -> str:
    """The current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def create_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for a prediction creation request."""
    payload: Dict[str, Any] = {
        "id": str(PREDICTION_ID),
        "status": "pending_upload",
        "created_at": _now(),
        "space_id": str(SPACE_ID),
        "lab_id": None,
        "user_id": None,
        "account_id": None,
        "guest_id": None,
        "space_name": "Test Space",
        "lab_name": None,
        "user_name": None,
        "account_name": None,
        "media_type": "image/png",
        "upload_data": {
            "url": UPLOAD_URL,
            "fields": {"key": "uploads/abc", "Content-Type": "image/png"},
        },
    }
    payload.update(overrides)
    return payload


def status_response(status: str = "completed", **overrides: Any) -> Dict[str, Any]:
    """A mock status response for a prediction."""
    payload: Dict[str, Any] = {
        "id": str(PREDICTION_ID),
        "status": status,
        "user_id": None,
        "account_id": None,
        "guest_id": None,
    }
    payload.update(overrides)
    return payload


def confirm_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for confirming an upload."""
    payload = create_response()
    payload.pop("upload_data")
    payload["status"] = "processing"
    payload.update(overrides)
    return payload


def result_item(**overrides: Any) -> Dict[str, Any]:
    """One entry of a prediction result payload."""
    payload: Dict[str, Any] = {
        "target_id": str(TARGET_ID),
        "score": 87,
        "label": "Deepfake",
        "description": "Likely synthetic",
        "media_url": "https://cdn.test.invalid/media/abc.png",
        "media_key": "media/abc.png",
    }
    payload.update(overrides)
    return payload


def detail_response(
    status: str = "completed",
    results: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A mock detail response for a prediction."""
    if results is None:
        results = [result_item()]
    payload: Dict[str, Any] = {
        "id": str(PREDICTION_ID),
        "status": status,
        "created_at": _now(),
        "updated_at": _now(),
        "space_id": str(SPACE_ID),
        "lab_id": None,
        "predictor_id": str(uuid4()),
        "runner_id": None,
        "user_id": None,
        "account_id": None,
        "guest_id": None,
        "media_type": "image/png",
        "media_size": 1024,
        "payed_tokens": 3,
        "result_payload": {"results": results},
        "space_name": "Test Space",
        "lab_name": None,
        "predictor_name": "default",
        "runner_name": None,
        "user_name": None,
        "account_name": None,
    }
    payload.update(overrides)
    return payload


def space_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for a space in a listing."""
    payload: Dict[str, Any] = {
        "id": str(SPACE_ID),
        "status": "active",
        "created_at": _now(),
        "name": "Test Space",
        "description": "A space for testing",
        "slug": "test-space",
        "url_id": "abc123",
        "is_default": True,
        "is_public": False,
        "user_id": None,
        "user_name": None,
        "organization_id": str(ORG_ID),
        "organization_name": "Test Org",
        "predictor_id": str(PREDICTOR_ID),
        "predictor_name": "default",
        "enabled_media": ["image", "video"],
        "enabled_target_names": ["Deepfake", "Violence"],
    }
    payload.update(overrides)
    return payload


def target_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for a detection target."""
    payload: Dict[str, Any] = {
        "id": str(TARGET_ID),
        "status": "active",
        "name": "Deepfake",
        "description": "Detects synthetic media",
        "reactions": {"1": "Real photo", "2": "AI generated"},
    }
    payload.update(overrides)
    return payload


def space_detail_response(**overrides: Any) -> Dict[str, Any]:
    """A mock detail response for a space."""
    payload = space_response()
    payload.pop("enabled_target_names")
    payload.update(
        {
            "predictor_multiplier": 3,
            "max_media_size": 52428800,
            "enabled_targets": [target_response()],
            "target_thresholds": [
                {
                    "target_id": str(TARGET_ID),
                    "blur_threshold": 50,
                    "hide_threshold": 80,
                }
            ],
        }
    )
    payload.update(overrides)
    return payload


def predictor_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for a predictor."""
    payload: Dict[str, Any] = {
        "id": str(PREDICTOR_ID),
        "name": "Default Predictor",
        "status": "active",
        "description": "The standard detection model",
        "token_multiplier": 3,
        "slug": "default-predictor",
        "url_id": "pred123",
        "supported_media": ["image", "video"],
        "supported_target_ids": [str(TARGET_ID)],
    }
    payload.update(overrides)
    return payload


def reaction_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for a reaction."""
    payload: Dict[str, Any] = {
        "id": str(REACTION_ID),
        "created_at": _now(),
        "prediction_id": str(PREDICTION_ID),
        "target_id": str(TARGET_ID),
        "is_positive": True,
        "key_value": None,
        "description": None,
    }
    payload.update(overrides)
    return payload


def share_response(**overrides: Any) -> Dict[str, Any]:
    """A mock response for a share."""
    payload: Dict[str, Any] = {
        "id": str(SHARE_ID),
        "created_at": _now(),
        "expired_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "prediction_id": str(PREDICTION_ID),
        "target_id": str(TARGET_ID),
        "expires_in": 7,
        "share_url": "https://elhio.com/s/abc123",
        "media_url": "https://cdn.test.invalid/media/abc.png",
        "target_name": "Deepfake",
        "space_name": "Test Space",
        "result": result_item(),
    }
    payload.update(overrides)
    return payload


def page_response(
    items: List[Dict[str, Any]], count: Optional[int] = None
) -> Dict[str, Any]:
    """A mock response every list endpoint returns."""
    return {"data": items, "count": len(items) if count is None else count}


def mock_lifecycle(status: str = "completed", results=None):
    """
    Wire every route a cloud analysis touches, and return the routes by name.

    Args:
        status: The terminal status the prediction reaches.
        results: The result items the completed prediction carries.

    Returns:
        The respx routes, so a test can assert which ones were called.
    """
    import httpx
    import respx

    return {
        "create": respx.post(PREDICTIONS_URL).mock(
            return_value=httpx.Response(200, json=create_response())
        ),
        "upload": respx.post(UPLOAD_URL).mock(return_value=httpx.Response(204)),
        "confirm": respx.post(f"{PREDICTIONS_URL}/{PREDICTION_ID}/confirm").mock(
            return_value=httpx.Response(200, json=confirm_response())
        ),
        "status": respx.get(f"{PREDICTIONS_URL}/{PREDICTION_ID}/status").mock(
            return_value=httpx.Response(200, json=status_response(status))
        ),
        "detail": respx.get(f"{PREDICTIONS_URL}/{PREDICTION_ID}").mock(
            return_value=httpx.Response(
                200, json=detail_response(status, results=results)
            )
        ),
    }


@pytest.fixture(autouse=True)
def isolate_env(tmp_path, monkeypatch):
    """
    Insulate every test from the developer's real environment.

    Both the client and this server read `GUARD_*` variables and walk up from the
    working directory looking for a `.env`. Without this, a developer with a real API
    key in either place would run the suite against production.
    """
    for key in [k for k in os.environ if k.startswith(("GUARD_", "FASTMCP_"))]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    reset_settings()
    yield
    reset_settings()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Keep polling tests from actually waiting."""

    async def _async_sleep(_):
        return None

    monkeypatch.setattr("guard_client.predictions.asyncio.sleep", _async_sleep)


@pytest.fixture
def settings(tmp_path) -> GuardMCPSettings:
    """
    Server settings pointed at the temp directory, installed as the process settings.

    Returns:
        The settings every tool will see for the duration of the test.
    """
    configured = GuardMCPSettings(
        media_roots=[tmp_path],
        max_media_bytes=1024 * 1024,
        default_poll_timeout=5.0,
        mask_error_details=False,
        enable_tasks=False,
    )
    reset_settings(configured)
    return configured


@pytest.fixture
def cloud_env(monkeypatch):
    """Credentials that make the client build a cloud client against the mock API."""
    monkeypatch.setenv("GUARD_API_KEY", API_KEY)
    monkeypatch.setenv("GUARD_BASE_URL", BASE_URL)
    monkeypatch.setenv("GUARD_SPACE_ID", str(SPACE_ID))
    monkeypatch.setenv("GUARD_MAX_RETRIES", "0")


@pytest.fixture
def png(tmp_path):
    """A PNG file inside the allowed media root."""
    path = tmp_path / "photo.png"
    path.write_bytes(png_bytes())
    return path


@pytest.fixture
def server(settings, cloud_env):
    """A fully wired server whose client talks to the mocked API."""
    from guard_mcp.server import create_server

    return create_server(settings)


@pytest.fixture
def client(server):
    """An in-memory MCP client connected to the server."""
    from fastmcp.client import Client

    return Client(server)
