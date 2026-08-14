"""
Translation from `guard_client` exceptions into MCP tool errors.

An agent cannot read a traceback and cannot inspect an exception's attributes. All it
sees is the text of the error, so every message produced here says what went wrong and
what to do next: which environment variable to set, which tool to call instead, whether
retrying is worthwhile at all.

The mapping is exhaustive over the client's public hierarchy and falls back to the
base `GuardError`, so a new exception type added upstream still produces a sane
message instead of leaking a masked internal error.

Examples:
    ```python
    from guard_client import GuardAuthError
    from guard_mcp.errors import to_tool_error

    try:
        await client.analyze("photo.jpg")
    except GuardError as exc:
        raise to_tool_error(exc) from exc
    ```
"""

from __future__ import annotations

from typing import Optional

from fastmcp.exceptions import ToolError
from guard_client import (
    SUPPORTED_MEDIA_TYPES,
    ActivityFailedError,
    GuardAPIError,
    GuardAuthError,
    GuardConflictError,
    GuardConnectionError,
    GuardError,
    GuardLocalEngineError,
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
    UnsupportedMediaTypeError,
)

__all__ = ["MediaAccessError", "configuration_error", "to_tool_error"]


class MediaAccessError(ToolError):
    """
    A media path was rejected before any work was attempted.

    This is a `ToolError`, so the message always reaches the agent even when
    `mask_error_details` is on. It is raised by `guard_mcp.media` for paths that do not
    exist, are not files, sit outside the configured roots, or are too large.
    """


def _local_engine_hint() -> str:
    """
    The install instruction for the optional on-device engine.

    Returns:
        A sentence naming the extra to install and the license that comes with it.
    """
    return (
        'Install it with: pip install "guard-mcp-server[local]" '
        "(the on-device engine is licensed AGPL-3.0-only, unlike the rest of this "
        "server). Alternatively call this tool with engine='cloud'."
    )


def _supported_types() -> str:
    """
    The accepted media types, ready to interpolate into a message.

    Returns:
        A comma separated list of MIME types the client can handle.
    """
    return ", ".join(sorted(str(item) for item in SUPPORTED_MEDIA_TYPES))


def _request_suffix(exc: GuardAPIError) -> str:
    """
    A trailing reference to the server request id, when there is one.

    Args:
        exc: The API error carrying the id.

    Returns:
        A parenthesized request id, or an empty string.
    """
    return f" (request id: {exc.request_id})" if exc.request_id else ""


def to_tool_error(exc: GuardError) -> ToolError:
    """
    Convert a client exception into a `ToolError` an agent can act on.

    Args:
        exc: Any exception from the `guard_client` hierarchy.

    Returns:
        A `ToolError` whose message explains the failure and the next step. The
        original exception should still be chained with `raise ... from exc` so the
        traceback survives in the server log.

    Notes:
        Ordering matters. The checks run from the most specific subclass to the most
        general, because `GuardAuthError` and friends all derive from `GuardAPIError`.
    """
    if isinstance(exc, LocalEngineNotInstalledError):
        return ToolError(
            f"The on-device engine is not installed. {_local_engine_hint()}"
        )
    if isinstance(exc, GuardLocalModelError):
        return ToolError(
            f"The on-device model could not be loaded: {exc}. Check "
            "GUARD_LOCAL_MODEL_PATH, or use engine='cloud'."
        )
    if isinstance(exc, GuardMediaDecodeError):
        return ToolError(
            f"The on-device engine could not decode this media: {exc}. The file may be "
            "corrupt or use an unsupported encoding."
        )
    if isinstance(exc, GuardLocalEngineError):
        return ToolError(f"The on-device engine failed: {exc}.")

    if isinstance(exc, UnsupportedMediaTypeError):
        return ToolError(
            f"Unsupported media type: {exc}. Supported: {_supported_types()}."
        )

    if isinstance(exc, ActivityFailedError):
        return ToolError(
            f"Processing ended as '{exc.status}' for activity {exc.activity_id}. "
            "This activity will not produce a result. Submit the media again to retry."
        )
    if isinstance(exc, GuardTimeoutError):
        return ToolError(
            f"Processing did not finish in time for activity {exc.activity_id}. It may "
            "still complete: call get_activity with that id in a little while, or "
            "retry with a larger timeout."
        )

    if isinstance(exc, GuardAuthError):
        return ToolError(
            "The Guard API rejected the credentials. Set a valid GUARD_API_KEY in the "
            f"environment of this MCP server and restart it{_request_suffix(exc)}."
        )
    if isinstance(exc, GuardPaymentRequiredError):
        return ToolError(
            f"The Guard account cannot serve this request: {exc}. This means no active "
            "subscription, no remaining tokens, or a plan limit was reached. Use "
            "estimate_tokens to check what a call would use"
            f"{_request_suffix(exc)}."
        )
    if isinstance(exc, GuardRateLimitError):
        wait = (
            f" Retry after about {exc.retry_after:.0f} seconds."
            if exc.retry_after
            else " Retry shortly."
        )
        return ToolError(f"The Guard API rate limit was exceeded.{wait}")
    if isinstance(exc, GuardNotFoundError):
        return ToolError(
            f"No such resource: {exc}. Check the id. Note the API answers 404 for "
            f"resources that exist but belong to another account{_request_suffix(exc)}."
        )
    if isinstance(exc, GuardConflictError):
        return ToolError(
            f"This action clashes with something that already exists: {exc}. It was "
            "most likely already done."
        )
    if isinstance(exc, GuardValidationError):
        fields = "; ".join(str(item) for item in exc.errors) or str(exc)
        return ToolError(f"The Guard API rejected the request: {fields}.")
    if isinstance(exc, GuardServerError):
        return ToolError(
            f"The Guard API is having trouble: {exc}. This is transient, retrying in a "
            f"moment is reasonable{_request_suffix(exc)}."
        )
    if isinstance(exc, GuardUploadError):
        return ToolError(
            f"Uploading the media failed: {exc}. The upload link may have expired; "
            "submit the media again."
        )
    if isinstance(exc, GuardConnectionError):
        return ToolError(
            f"The Guard API could not be reached: {exc}. Check network access and "
            "GUARD_BASE_URL."
        )
    if isinstance(exc, GuardAPIError):
        return ToolError(
            f"The Guard API returned an error: {exc}{_request_suffix(exc)}."
        )

    return ToolError(str(exc) or "The Guard client reported an unspecified failure.")


def configuration_error(reason: Optional[str] = None) -> ToolError:
    """
    The error raised when the server has no usable Guard client.

    Args:
        reason: The message from the failure that prevented the client being built.

    Returns:
        A `ToolError` naming the environment variables that need setting.
    """
    detail = f" ({reason})" if reason else ""
    return ToolError(
        f"This server has no usable Guard client{detail}. Set GUARD_API_KEY (and "
        "usually GUARD_SPACE_ID) in the server environment and restart it, or set "
        "GUARD_ENGINE=local to run on-device without an API key. Read the "
        "guard://config resource to see what the server resolved."
    )
