"""
Serialization helpers shared by the tool modules.

Two jobs: turn the client's pydantic models into plain JSON-ready dictionaries with
the noise removed, and turn its `Page` objects into a page shape that tells an agent
whether to ask for more.

Examples:
    ```python
    from guard_mcp.utils import to_page

    page = await client.spaces.list(limit=20)
    return to_page(page, skip=0)
    ```
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from guard_client import MAX_LIMIT, ActivityDetail
from pydantic import BaseModel

from .schemas import ActivitySummary, ListPage, ResultItem

__all__ = ["clamp_limit", "to_activity_summary", "to_dict", "to_page"]

#: Fields that are large, short lived, or meaningless to an agent.
_NOISE_FIELDS = frozenset({"media_key", "media_url", "result_payload"})


def to_dict(model: BaseModel, *, drop: Iterable[str] = ()) -> Dict[str, Any]:
    """
    Render a model as a JSON-ready dictionary without empty or noisy fields.

    Args:
        model: Any pydantic model from the client.
        drop: Extra field names to remove on top of the default noise fields.

    Returns:
        The model's fields with `None` values, presigned URLs, and storage keys removed.
        UUIDs and datetimes come out as strings, so the result is safe to return
        straight from a tool.
    """
    removed = _NOISE_FIELDS.union(drop)
    dumped = model.model_dump(mode="json", exclude_none=True)
    return {key: value for key, value in dumped.items() if key not in removed}


def to_page(page: Any, *, skip: int, drop: Iterable[str] = ()) -> ListPage:
    """
    Convert a client `Page` into the listing shape tools return.

    Args:
        page: A `Page` of any record type.
        skip: The offset that produced this page, used to compute the next one.
        drop: Extra field names to remove from each record.

    Returns:
        A `ListPage` carrying the trimmed records and the offset for the next page.

    Note:
        `Page` implements `__iter__` over its items, so `dict(page)` and
        `list(page)` mean different things. This uses the item list explicitly.
    """
    items = [to_dict(item, drop=drop) for item in page.data]
    has_more = bool(getattr(page, "has_more", False))
    return ListPage(
        items=items,
        count=page.count,
        has_more=has_more,
        next_skip=skip + len(items) if has_more else None,
    )


def clamp_limit(limit: Optional[int], *, default: int = 20) -> int:
    """
    Keep a caller-supplied page size inside what the API accepts.

    Args:
        limit: The requested page size, if any.
        default: The size to use when none was requested.

    Returns:
        A page size between 1 and the API maximum of 100.
    """
    if limit is None:
        return default
    return max(1, min(int(limit), MAX_LIMIT))


def to_activity_summary(detail: ActivityDetail) -> ActivitySummary:
    """
    Summarize a stored activity, including its results when it has them.

    Args:
        detail: The activity as the API returned it.

    Returns:
        An `ActivitySummary`. `results` is empty while the activity is still processing,
        or when it failed before producing any.
    """
    payload = detail.result_payload
    return ActivitySummary(
        id=detail.id,
        status=detail.status,
        created_at=detail.created_at,
        media_type=detail.media_type,
        space_id=detail.space_id,
        space_name=detail.space_name,
        payed_tokens=detail.payed_tokens,
        results=[ResultItem.from_item(item) for item in payload.results]
        if payload
        else [],
    )
