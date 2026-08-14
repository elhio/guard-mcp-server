"""
Tests for the media path guard.

The containment check is the one thing standing between an agent and every readable
file on the machine, so it is tested against the ways a path can lie about where it
points.
"""

from __future__ import annotations

import pytest

from conftest import png_bytes
from guard_mcp.errors import MediaAccessError
from guard_mcp.media import describe_media, resolve_media_path
from guard_mcp.settings import GuardMCPSettings


def test_accepts_a_file_inside_a_root(settings, png):
    """
    Verify that a valid file inside an allowed root directory resolves successfully.
    """
    assert resolve_media_path(str(png), settings=settings) == png.resolve()


def test_rejects_a_path_outside_every_root(settings, tmp_path_factory):
    """Verify that paths sitting outside all configured media roots are rejected."""
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.png"
    outside.write_bytes(png_bytes())

    with pytest.raises(MediaAccessError, match="not allowed"):
        resolve_media_path(str(outside), settings=settings)


def test_rejects_traversal_out_of_a_root(settings, tmp_path, tmp_path_factory):
    """Verify that relative path traversal attempting to break out of a root fails."""
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.png"
    outside.write_bytes(png_bytes())
    traversal = tmp_path / ".." / outside.parent.name / "secret.png"

    with pytest.raises(MediaAccessError, match="not allowed"):
        resolve_media_path(str(traversal), settings=settings)


def test_rejects_a_symlink_pointing_out_of_a_root(settings, tmp_path, tmp_path_factory):
    """Verify that symlinks resolving to targets outside allowed roots are rejected."""
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.png"
    outside.write_bytes(png_bytes())
    link = tmp_path / "innocent.png"
    link.symlink_to(outside)

    with pytest.raises(MediaAccessError, match="not allowed"):
        resolve_media_path(str(link), settings=settings)


def test_allows_anything_when_the_check_is_disabled(tmp_path_factory):
    """Verify that any path is allowed when `allow_any_path` is explicitly enabled."""
    outside = tmp_path_factory.mktemp("elsewhere") / "photo.png"
    outside.write_bytes(png_bytes())
    settings = GuardMCPSettings(allow_any_path=True)

    assert resolve_media_path(str(outside), settings=settings) == outside.resolve()


def test_rejects_a_missing_file(settings, tmp_path):
    """Verify that attempting to resolve a non-existent file path raises an error."""
    with pytest.raises(MediaAccessError, match="No such file"):
        resolve_media_path(str(tmp_path / "nope.png"), settings=settings)


def test_rejects_a_directory(settings, tmp_path):
    """Verify that passing a directory path instead of a file raises an error."""
    with pytest.raises(MediaAccessError, match="directory"):
        resolve_media_path(str(tmp_path), settings=settings)


def test_rejects_an_empty_path(settings):
    """Verify that empty or whitespace-only paths are rejected."""
    with pytest.raises(MediaAccessError, match="No media path"):
        resolve_media_path("   ", settings=settings)


def test_rejects_an_empty_file(settings, tmp_path):
    """Verify that 0-byte media files are rejected prior to processing."""
    empty = tmp_path / "empty.png"
    empty.touch()

    with pytest.raises(MediaAccessError, match="empty"):
        resolve_media_path(str(empty), settings=settings)


def test_rejects_a_file_over_the_size_limit(tmp_path):
    """Verify that files exceeding `max_media_bytes` are rejected before reading."""
    big = tmp_path / "big.png"
    big.write_bytes(png_bytes() * 100)
    settings = GuardMCPSettings(media_roots=[tmp_path], max_media_bytes=10)

    with pytest.raises(MediaAccessError, match="over this server's limit"):
        resolve_media_path(str(big), settings=settings)


def test_describe_media_reads_the_header(settings, png):
    """Verify that `describe_media` correctly probes the MIME type and dimensions."""
    info = describe_media(resolve_media_path(str(png), settings=settings))

    assert info.media_type == "image/png"
    assert info.width == 1
    assert info.height == 1


def test_describe_media_rejects_an_unsupported_type(settings, tmp_path):
    """Verify that non-media file types (e.g. plain text) are rejected by the probe."""
    text = tmp_path / "notes.txt"
    text.write_text("not media")

    with pytest.raises(MediaAccessError, match="not a supported media type"):
        describe_media(resolve_media_path(str(text), settings=settings))


async def test_the_tool_reports_a_rejected_path(client, tmp_path_factory):
    """Verify that calling the `analyze_media` tool with an illegal path raises."""
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.png"
    outside.write_bytes(png_bytes())

    async with client as session:
        with pytest.raises(Exception, match="not allowed"):
            await session.call_tool("analyze_media", {"path": str(outside)})
