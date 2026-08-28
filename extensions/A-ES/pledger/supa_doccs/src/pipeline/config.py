"""Pipeline configuration loader with defaults and validation.

Provides load_config() which creates a validated PipelineConfig from
optional user overrides merged onto sensible defaults.
"""

from typing import TypedDict


class PipelineConfig(TypedDict):
    """Configuration parameters for the document-intelligence pipeline.

    All values are frozen into runs.config_snapshot at run creation
    and read from state["config"] during execution.
    """

    max_retries: int  # default: 3
    chunk_max_size: int  # default: 1000 characters
    chunk_overlap: int  # default: 200 characters
    confidence_threshold: float  # default: 0.7
    review_timeout_hours: int  # default: 72
    reminder_interval_hours: int  # default: 24
    poll_interval_seconds: int  # default: 30
    extract_text_timeout_seconds: int  # default: 60
    min_chunk_threshold: int  # default: 200 characters


_DEFAULTS: PipelineConfig = {
    "max_retries": 3,
    "chunk_max_size": 1000,
    "chunk_overlap": 200,
    "confidence_threshold": 0.7,
    "review_timeout_hours": 72,
    "reminder_interval_hours": 24,
    "poll_interval_seconds": 30,
    "extract_text_timeout_seconds": 60,
    "min_chunk_threshold": 200,
}


def load_config(overrides: dict | None = None) -> PipelineConfig:
    """Load pipeline configuration with defaults, applying optional overrides.

    Args:
        overrides: Dictionary of config keys to override. Keys must be valid
            PipelineConfig fields. None or empty dict uses all defaults.

    Returns:
        A validated PipelineConfig with defaults merged with overrides.

    Raises:
        ValueError: If any constraint is violated or an unknown key is provided.
    """
    config: PipelineConfig = {**_DEFAULTS}  # type: ignore[typeddict-item]

    if overrides:
        valid_keys = set(PipelineConfig.__annotations__.keys())
        unknown_keys = set(overrides.keys()) - valid_keys
        if unknown_keys:
            raise ValueError(
                f"Unknown configuration keys: {sorted(unknown_keys)}"
            )
        config.update(overrides)  # type: ignore[typeddict-item]

    _validate(config)
    return config


def _validate(config: PipelineConfig) -> None:
    """Validate all configuration constraints.

    Raises:
        ValueError: If any constraint is violated.
    """
    errors: list[str] = []

    # max_retries >= 0
    if config["max_retries"] < 0:
        errors.append(
            f"max_retries must be >= 0, got {config['max_retries']}"
        )

    # chunk_max_size > chunk_overlap > 0
    if config["chunk_max_size"] <= 0:
        errors.append(
            f"chunk_max_size must be > 0, got {config['chunk_max_size']}"
        )
    if config["chunk_overlap"] <= 0:
        errors.append(
            f"chunk_overlap must be > 0, got {config['chunk_overlap']}"
        )
    if config["chunk_max_size"] <= config["chunk_overlap"]:
        errors.append(
            f"chunk_max_size ({config['chunk_max_size']}) must be greater than "
            f"chunk_overlap ({config['chunk_overlap']})"
        )

    # 0.0 <= confidence_threshold <= 1.0
    if not (0.0 <= config["confidence_threshold"] <= 1.0):
        errors.append(
            f"confidence_threshold must be between 0.0 and 1.0, "
            f"got {config['confidence_threshold']}"
        )

    # Positive integer constraints for timeouts and intervals
    if config["review_timeout_hours"] <= 0:
        errors.append(
            f"review_timeout_hours must be > 0, got {config['review_timeout_hours']}"
        )
    if config["reminder_interval_hours"] <= 0:
        errors.append(
            f"reminder_interval_hours must be > 0, got {config['reminder_interval_hours']}"
        )
    if config["poll_interval_seconds"] <= 0:
        errors.append(
            f"poll_interval_seconds must be > 0, got {config['poll_interval_seconds']}"
        )
    if config["extract_text_timeout_seconds"] <= 0:
        errors.append(
            f"extract_text_timeout_seconds must be > 0, "
            f"got {config['extract_text_timeout_seconds']}"
        )

    # min_chunk_threshold > 0
    if config["min_chunk_threshold"] <= 0:
        errors.append(
            f"min_chunk_threshold must be > 0, got {config['min_chunk_threshold']}"
        )

    if errors:
        raise ValueError(
            "Invalid pipeline configuration:\n- " + "\n- ".join(errors)
        )
