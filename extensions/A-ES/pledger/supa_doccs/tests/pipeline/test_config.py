"""Tests for pipeline configuration loader."""

import pytest

from src.pipeline.config import PipelineConfig, load_config


class TestLoadConfigDefaults:
    """Tests that load_config returns correct defaults with no overrides."""

    def test_returns_all_default_values(self):
        config = load_config()
        assert config["max_retries"] == 3
        assert config["chunk_max_size"] == 1000
        assert config["chunk_overlap"] == 200
        assert config["confidence_threshold"] == 0.7
        assert config["review_timeout_hours"] == 72
        assert config["reminder_interval_hours"] == 24
        assert config["poll_interval_seconds"] == 30
        assert config["extract_text_timeout_seconds"] == 60
        assert config["min_chunk_threshold"] == 200

    def test_returns_all_expected_keys(self):
        config = load_config()
        expected_keys = set(PipelineConfig.__annotations__.keys())
        assert set(config.keys()) == expected_keys

    def test_empty_overrides_returns_defaults(self):
        config = load_config({})
        assert config == load_config()

    def test_none_overrides_returns_defaults(self):
        config = load_config(None)
        assert config == load_config()


class TestLoadConfigOverrides:
    """Tests that overrides are applied correctly."""

    def test_single_override(self):
        config = load_config({"max_retries": 5})
        assert config["max_retries"] == 5
        # Other defaults remain
        assert config["chunk_max_size"] == 1000

    def test_multiple_overrides(self):
        config = load_config({
            "max_retries": 10,
            "chunk_max_size": 2000,
            "chunk_overlap": 400,
            "confidence_threshold": 0.9,
        })
        assert config["max_retries"] == 10
        assert config["chunk_max_size"] == 2000
        assert config["chunk_overlap"] == 400
        assert config["confidence_threshold"] == 0.9

    def test_unknown_key_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown configuration keys"):
            load_config({"nonexistent_key": 42})

    def test_override_with_boundary_values(self):
        config = load_config({
            "max_retries": 0,
            "confidence_threshold": 0.0,
        })
        assert config["max_retries"] == 0
        assert config["confidence_threshold"] == 0.0


class TestLoadConfigValidation:
    """Tests that validation catches invalid configurations."""

    def test_negative_max_retries(self):
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            load_config({"max_retries": -1})

    def test_zero_chunk_max_size(self):
        with pytest.raises(ValueError, match="chunk_max_size must be > 0"):
            load_config({"chunk_max_size": 0})

    def test_negative_chunk_max_size(self):
        with pytest.raises(ValueError, match="chunk_max_size must be > 0"):
            load_config({"chunk_max_size": -5})

    def test_zero_chunk_overlap(self):
        with pytest.raises(ValueError, match="chunk_overlap must be > 0"):
            load_config({"chunk_overlap": 0})

    def test_negative_chunk_overlap(self):
        with pytest.raises(ValueError, match="chunk_overlap must be > 0"):
            load_config({"chunk_overlap": -10})

    def test_chunk_overlap_equals_chunk_max_size(self):
        with pytest.raises(ValueError, match="chunk_max_size.*must be greater than.*chunk_overlap"):
            load_config({"chunk_max_size": 500, "chunk_overlap": 500})

    def test_chunk_overlap_exceeds_chunk_max_size(self):
        with pytest.raises(ValueError, match="chunk_max_size.*must be greater than.*chunk_overlap"):
            load_config({"chunk_max_size": 200, "chunk_overlap": 300})

    def test_confidence_threshold_above_one(self):
        with pytest.raises(ValueError, match="confidence_threshold must be between"):
            load_config({"confidence_threshold": 1.5})

    def test_confidence_threshold_below_zero(self):
        with pytest.raises(ValueError, match="confidence_threshold must be between"):
            load_config({"confidence_threshold": -0.1})

    def test_zero_review_timeout_hours(self):
        with pytest.raises(ValueError, match="review_timeout_hours must be > 0"):
            load_config({"review_timeout_hours": 0})

    def test_zero_reminder_interval_hours(self):
        with pytest.raises(ValueError, match="reminder_interval_hours must be > 0"):
            load_config({"reminder_interval_hours": 0})

    def test_zero_poll_interval_seconds(self):
        with pytest.raises(ValueError, match="poll_interval_seconds must be > 0"):
            load_config({"poll_interval_seconds": 0})

    def test_zero_extract_text_timeout_seconds(self):
        with pytest.raises(ValueError, match="extract_text_timeout_seconds must be > 0"):
            load_config({"extract_text_timeout_seconds": 0})

    def test_zero_min_chunk_threshold(self):
        with pytest.raises(ValueError, match="min_chunk_threshold must be > 0"):
            load_config({"min_chunk_threshold": 0})

    def test_multiple_errors_reported_together(self):
        with pytest.raises(ValueError) as exc_info:
            load_config({
                "max_retries": -1,
                "chunk_max_size": 0,
                "confidence_threshold": 2.0,
            })
        error_msg = str(exc_info.value)
        assert "max_retries" in error_msg
        assert "chunk_max_size" in error_msg
        assert "confidence_threshold" in error_msg

    def test_valid_boundary_confidence_one(self):
        config = load_config({"confidence_threshold": 1.0})
        assert config["confidence_threshold"] == 1.0

    def test_valid_boundary_confidence_zero(self):
        config = load_config({"confidence_threshold": 0.0})
        assert config["confidence_threshold"] == 0.0
