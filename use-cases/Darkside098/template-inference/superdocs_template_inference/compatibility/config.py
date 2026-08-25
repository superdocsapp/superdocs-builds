"""Configuration for pairwise compatibility scoring."""

import math
from dataclasses import dataclass


@dataclass
class CompatibilityConfig:
    """Configuration for deterministic pairwise document compatibility."""

    weight_block_structure: float = 0.15
    weight_block_sequence: float = 0.12
    weight_heading_distribution: float = 0.12
    weight_section_count: float = 0.08
    weight_section_structure: float = 0.05
    weight_vocabulary_overlap: float = 0.20
    weight_heading_vocabulary: float = 0.10
    weight_table_structure: float = 0.10
    weight_document_length: float = 0.08
    compatibility_threshold: float = 0.65

    def __post_init__(self) -> None:
        """Validate configuration values and normalized weights."""
        values = {
            "weight_block_structure": self.weight_block_structure,
            "weight_block_sequence": self.weight_block_sequence,
            "weight_heading_distribution": self.weight_heading_distribution,
            "weight_section_count": self.weight_section_count,
            "weight_section_structure": self.weight_section_structure,
            "weight_vocabulary_overlap": self.weight_vocabulary_overlap,
            "weight_heading_vocabulary": self.weight_heading_vocabulary,
            "weight_table_structure": self.weight_table_structure,
            "weight_document_length": self.weight_document_length,
            "compatibility_threshold": self.compatibility_threshold,
        }

        for name, value in values.items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be a finite float")

        for name, value in {
            "weight_block_structure": self.weight_block_structure,
            "weight_block_sequence": self.weight_block_sequence,
            "weight_heading_distribution": self.weight_heading_distribution,
            "weight_section_count": self.weight_section_count,
            "weight_section_structure": self.weight_section_structure,
            "weight_vocabulary_overlap": self.weight_vocabulary_overlap,
            "weight_heading_vocabulary": self.weight_heading_vocabulary,
            "weight_table_structure": self.weight_table_structure,
            "weight_document_length": self.weight_document_length,
        }.items():
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")

        threshold = self.compatibility_threshold
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("compatibility_threshold must be between 0.0 and 1.0")

        weight_total = (
            self.weight_block_structure
            + self.weight_block_sequence
            + self.weight_heading_distribution
            + self.weight_section_count
            + self.weight_section_structure
            + self.weight_vocabulary_overlap
            + self.weight_heading_vocabulary
            + self.weight_table_structure
            + self.weight_document_length
        )

        if abs(weight_total - 1.0) > 1e-9:
            raise ValueError(f"Compatibility weights must sum to 1.0; got {weight_total}")
