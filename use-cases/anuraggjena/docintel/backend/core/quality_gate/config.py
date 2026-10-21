from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class QualityGateSettings:
    """Runtime settings for a quality gate run."""
    enabled: bool = True
    block_on_failure: bool = False
    enabled_checks: Optional[List[str]] = None
    checks_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_db_config(cls, config) -> "QualityGateSettings":
        """Build from a QualityGateConfig ORM object."""
        if config is None:
            return cls()
        return cls(
            enabled=config.enabled,
            block_on_failure=config.block_on_failure,
            checks_config=config.checks_config or {}
        )

    @classmethod
    def default(cls) -> "QualityGateSettings":
        return cls()
