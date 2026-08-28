"""JSONB serialization/deserialization for PipelineState.

Handles bytes ↔ base64 conversion for raw_content, ensuring round-trip
fidelity when storing PipelineState as JSONB in PostgreSQL checkpoints.
"""

import base64
from typing import Any

from src.pipeline.state import PipelineState


def serialize_state(state: PipelineState) -> dict[str, Any]:
    """Convert a PipelineState to a JSON-serializable dict.

    Transforms:
        - raw_content (bytes | None) → base64-encoded string | None

    All other fields are already JSON-native (str, int, float, bool, None,
    list, dict) and pass through unchanged.

    Args:
        state: The PipelineState to serialize.

    Returns:
        A dict safe for JSONB storage.
    """
    data: dict[str, Any] = dict(state)

    # bytes → base64 string
    raw = data.get("raw_content")
    if raw is not None:
        data["raw_content"] = base64.b64encode(raw).decode("ascii")

    return data


def deserialize_state(data: dict[str, Any]) -> PipelineState:
    """Reconstruct a PipelineState from a JSONB dict.

    Transforms:
        - raw_content (base64 string | None) → bytes | None

    All other fields pass through unchanged.

    Args:
        data: The JSONB dict loaded from a checkpoint.

    Returns:
        A valid PipelineState instance.
    """
    result = dict(data)

    # base64 string → bytes
    raw = result.get("raw_content")
    if raw is not None:
        result["raw_content"] = base64.b64decode(raw.encode("ascii"))

    return PipelineState(**result)  # type: ignore[typeddict-item]
