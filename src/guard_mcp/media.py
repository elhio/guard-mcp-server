"""
Path handling for media an agent asks this server to moderate.

Tools accept a filesystem path and nothing else. No URLs, because fetching one turns the
server into a request forwarder that an agent can point at internal addresses. No inline
base64, because a video does not belong in a model's context window.

That leaves one thing to get right: an agent must not be able to talk this server into
reading arbitrary files. Every path passes through `resolve_media_path`, which resolves
symlinks first and then checks containment against the configured roots, so
`../../.ssh/id_rsa` and a symlink pointing there both fail the same check.

Examples:
    ```python
    from guard_mcp.media import describe_media, resolve_media_path

    path = resolve_media_path("photo.jpg")
    info = describe_media(path)
    print(info.media_type, info.width, info.height)
    ```
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from guard_client import MediaInfo, UnsupportedMediaTypeError, probe_media

from .errors import MediaAccessError
from .settings import GuardMCPSettings, get_settings

__all__ = ["describe_media", "resolve_media_path"]


def _format_size(num_bytes: int) -> str:
    """
    Render a byte count the way a person would say it.

    Args:
        num_bytes: The size to render.

    Returns:
        A short string such as `4.2 MB`.
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _is_contained(path: Path, root: Path) -> bool:
    """
    Whether a resolved path sits inside a resolved root.

    Args:
        path: The candidate file, already resolved.
        root: An allowed directory, already resolved.

    Returns:
        True when `path` is `root` or lives beneath it.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_media_path(
    raw_path: str, *, settings: Optional[GuardMCPSettings] = None
) -> Path:
    """
    Turn a caller-supplied path into a vetted absolute path.

    Args:
        raw_path: The path as the agent wrote it. `~` is expanded and relative paths are
            taken against the server's working directory.
        settings: Overrides the process settings. Mainly for tests.

    Returns:
        The resolved path, guaranteed to exist, to be a regular file, to sit inside an
        allowed root, and to be within the size limit.

    Raises:
        MediaAccessError: The path is empty, missing, not a regular file, outside the
            configured roots, or larger than `GUARD_MCP_MAX_MEDIA_BYTES`.

    Notes:
        The size is read from the directory entry rather than by opening the file,
        because the client buffers the whole file into memory when it uploads. Finding
        out a file is too large after allocating it defeats the purpose of the limit.
    """
    settings = settings or get_settings()

    if not raw_path or not raw_path.strip():
        raise MediaAccessError("No media path was given.")

    path = Path(raw_path).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MediaAccessError(
            f"No such file: {raw_path}. Give an absolute path to a media file on the "
            "machine running this server."
        ) from exc

    if resolved.is_dir():
        raise MediaAccessError(
            f"{resolved} is a directory. Give the path of a single media file."
        )
    if not resolved.is_file():
        raise MediaAccessError(f"{resolved} is not a regular file.")

    if not settings.allow_any_path:
        roots = settings.resolved_media_roots()
        if not any(_is_contained(resolved, root) for root in roots):
            allowed = ", ".join(str(root) for root in roots)
            raise MediaAccessError(
                f"Reading {resolved} is not allowed. This server only accepts media "
                f"under: {allowed}. Move the file there, or set GUARD_MCP_MEDIA_ROOTS "
                "in the server environment."
            )

    size = resolved.stat().st_size
    if size == 0:
        raise MediaAccessError(f"{resolved} is empty.")
    if size > settings.max_media_bytes:
        raise MediaAccessError(
            f"{resolved} is {_format_size(size)}, over this server's limit of "
            f"{_format_size(settings.max_media_bytes)}. Raise "
            "GUARD_MCP_MAX_MEDIA_BYTES or submit a smaller file."
        )

    return resolved


def describe_media(path: Path) -> MediaInfo:
    """
    Read the media type and dimensions without decoding the file.

    Args:
        path: A path already vetted by `resolve_media_path`.

    Returns:
        The `MediaInfo` the client's header probe produced.

    Raises:
        MediaAccessError: The file is not a media type the Guard API accepts. Failing
            here saves an upload that the API would reject anyway.
    """
    try:
        return probe_media(str(path))
    except UnsupportedMediaTypeError as exc:
        raise MediaAccessError(
            f"{path.name} is not a supported media type: {exc}."
        ) from exc
