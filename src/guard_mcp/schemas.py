"""
The shapes tools return to an agent.

These mirror the client's own models. Field names, nesting and types are the ones
`guard_client` uses, so anything documented there reads the same here. What they drop is
plumbing an agent cannot act on: presigned upload data, storage keys, media URLs, runner
and predictor ids.

What they deliberately do not add is a decision. The API reports a score from 0 to 100
per detection target and nothing else; whether a given score is acceptable is a policy
this server has no way to know. `get_space` returns the space's own `target_thresholds`
for a caller that wants to apply one.

Examples:
    ```python
    from guard_mcp.schemas import AnalysisResult

    result = AnalysisResult.from_detection(detection)
    print(result.max_score, [item.label for item in result.results])
    ```
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from guard_client import (
    DetectionMatch,
    DetectionResult,
    Engine,
    MediaType,
    PredictionResultItem,
    PredictionStatus,
)
from pydantic import BaseModel, Field

__all__ = [
    "PredictionSummary",
    "AnalysisResult",
    "ListPage",
    "ResultItem",
]


class ResultItem(BaseModel):
    """
    What one detection target reported about the media.

    Attributes:
        target_id: The target this score belongs to. Cloud target ids come from the
            space; on-device ids are derived from the label and do not match them.
        score: How strongly the target matched, from 0 to 100. Higher means more
            strongly detected. It is not a probability.
        label: What the engine calls the result. On-device it is the target name, for
            example `Explicit`; the cloud API words a verdict in the request locale,
            for example `Strong Signs of Explicit Content`.
        description: The engine's summary, when it gave one.
        detected: The engine's own boolean verdict, which it reaches with a
            per-category cut-off of its own. Only the on-device engine sets it; the
            cloud API does not report one, so it is `null` there.
        matches: The evidence behind the score. On-device engine only.
    """

    target_id: UUID
    score: int
    label: str
    description: Optional[str] = None
    detected: Optional[bool] = None
    matches: List[DetectionMatch] = Field(default_factory=list)

    @classmethod
    def from_item(cls, item: PredictionResultItem) -> ResultItem:
        """
        Narrow one client result item to the fields worth showing.

        Args:
            item: One entry of the client's detection result.

        Returns:
            The same item without its storage key and media URL.
        """
        return cls(
            target_id=item.target_id,
            score=item.score,
            label=item.label,
            description=item.description,
            detected=item.detected,
            matches=list(item.matches or []),
        )


class AnalysisResult(BaseModel):
    """
    What the engines found in one piece of media.

    Attributes:
        engine: Which engine produced the result.
        prediction_id: The server side prediction, for follow-up calls. Always `null`
            for the on-device engine, which creates no prediction.
        max_score: The highest score across all results, or 0 when there are none.
        results: One entry per detection target that ran.
    """

    engine: Engine
    prediction_id: Optional[UUID] = None
    max_score: int = 0
    results: List[ResultItem] = Field(default_factory=list)

    @classmethod
    def from_detection(cls, detection: DetectionResult) -> AnalysisResult:
        """
        Reshape a client `DetectionResult` for an agent.

        Args:
            detection: The result of a completed analysis.

        Returns:
            The same result without the fields an agent cannot act on. `max_score` is
            the client's own property, not a recomputation.
        """
        return cls(
            engine=detection.engine,
            prediction_id=detection.prediction_id,
            max_score=detection.max_score,
            results=[ResultItem.from_item(item) for item in detection.results],
        )


class PredictionSummary(BaseModel):
    """
    A stored prediction with its results, trimmed for an agent.

    Attributes:
        id: The prediction id.
        status: One of `pending_upload`, `processing`, `completed`, `failed`,
            `canceled`.
        created_at: When the prediction was created.
        media_type: The MIME type that was analyzed.
        space_id: The space that processed it, or `null` for a lab's prediction.
        space_name: The name of that space.
        lab_id: The lab that processed it, or `null` for a space's prediction.
        lab_name: The name of that lab.
        payed_tokens: Tokens actually charged, once the API reported them.
        results: One entry per detection target, empty until processing completed.
    """

    id: UUID
    status: PredictionStatus
    created_at: Optional[datetime] = None
    media_type: Optional[MediaType] = None
    space_id: Optional[UUID] = None
    space_name: Optional[str] = None
    lab_id: Optional[UUID] = None
    lab_name: Optional[str] = None
    payed_tokens: Optional[int] = None
    results: List[ResultItem] = Field(default_factory=list)


class ListPage(BaseModel):
    """
    One page of a listing.

    Attributes:
        items: The records on this page, already trimmed.
        count: How many records match the filters in total.
        has_more: Whether another page exists.
        next_skip: The `skip` value that fetches the next page, when there is one.
    """

    items: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    has_more: bool = False
    next_skip: Optional[int] = None
