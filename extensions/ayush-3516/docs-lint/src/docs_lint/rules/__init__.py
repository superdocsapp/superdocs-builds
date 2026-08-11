"""Local, deterministic rules.

Importing this package registers the built-in rule set.
"""

from . import builtin  # noqa: F401  - import for its registration side effects
from .base import Rule, RuleBase, all_rules, get_rule, register, run_local_rules

__all__ = ["Rule", "RuleBase", "all_rules", "get_rule", "register", "run_local_rules"]
