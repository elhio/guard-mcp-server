"""
Tests for the on-device engine path.

The AGPL licensed `guard_local` package is never imported here. The client identifies
engine errors by module and class name rather than by importing the classes, so a
stand-in with the right `__module__` is enough to exercise the whole translation path
whether or not the extra is installed.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from guard_mcp.server import create_server


class _FakeEngine:
    """An engine that answers the way the real one does, in fixed target order."""

    def __init__(self, scores=(0.9, 0.1, 0.05)):
        self.scores = scores

    def analyze(self, data, media_type):
        labels = ("AI-Generated", "Violence", "Explicit")
        return [
            {
                "label": label,
                "score": score,
                "detected": score >= 0.5,
                "matches": [
                    {
                        "id": "m1",
                        "category": "aiGenerated",
                        "label": "diffusion artifacts",
                        "confidence": 88,
                        "source": "model",
                        "evidence": "x" * 4000,
                    }
                ],
            }
            for label, score in zip(labels, self.scores, strict=False)
        ]


@pytest.fixture
def local_server(settings, monkeypatch, tmp_path):
    """A server whose client runs on-device against the fake engine."""
    monkeypatch.delenv("GUARD_API_KEY", raising=False)
    monkeypatch.setenv("GUARD_ENGINE", "local")
    server = create_server(settings)

    from guard_client.local import LocalRunner

    monkeypatch.setattr(
        LocalRunner, "_ensure_engine", lambda self: _FakeEngine(), raising=True
    )
    return server


async def test_local_analysis_needs_no_network(local_server, png):
    async with Client(local_server) as session:
        result = await session.call_tool("analyze_media", {"path": str(png)})

    data = result.structured_content
    assert data["engine"] == "local"
    assert data["prediction_id"] is None
    assert data["max_score"] == 90
    assert [item["label"] for item in data["results"]] == [
        "AI-Generated",
        "Violence",
        "Explicit",
    ]


async def test_the_engines_own_detected_is_passed_through_untouched(local_server, png):
    """
    `detected` is the on-device engine's own per-category verdict.

    This server neither derives it nor overrides it. The cloud API reports no such
    field, so it stays null there.
    """
    async with Client(local_server) as session:
        result = await session.call_tool("analyze_media", {"path": str(png)})

    items = result.structured_content["results"]
    assert [item["detected"] for item in items] == [True, False, False]


async def test_match_evidence_survives_intact(local_server, png):
    """The client hands over the whole match, and so does this server."""
    async with Client(local_server) as session:
        result = await session.call_tool("analyze_media", {"path": str(png)})

    match = result.structured_content["results"][0]["matches"][0]
    assert match["confidence"] == 88
    assert match["id"] == "m1"
    assert match["evidence"] == "x" * 4000


async def test_a_missing_engine_explains_how_to_install_it(settings, monkeypatch, png):
    monkeypatch.delenv("GUARD_API_KEY", raising=False)
    monkeypatch.setenv("GUARD_ENGINE", "local")
    server = create_server(settings)

    from guard_client import LocalEngineNotInstalledError
    from guard_client.local import LocalRunner

    def _raise(self):
        raise LocalEngineNotInstalledError("guard_local is not installed")

    monkeypatch.setattr(LocalRunner, "_ensure_engine", _raise, raising=True)

    async with Client(server) as session:
        with pytest.raises(Exception, match=r"guard-mcp-server\[local\]"):
            await session.call_tool("analyze_media", {"path": str(png)})
