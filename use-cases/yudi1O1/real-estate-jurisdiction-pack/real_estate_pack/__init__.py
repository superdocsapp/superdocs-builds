"""Jurisdiction-aware residential lease and disclosure packs, built on SuperDocs.

Public surface, in the order a caller uses it:

    load_request        read a lease record from YAML
    load_ruleset        load one jurisdiction with the federal layer under it
    validate_pack       decide which rules fire; refuse if that is unanswerable
    assemble            build the three cross-referenced documents
    check_consistency   prove the three documents agree
    draft_pack          lay them onto a customer template through SuperDocs
"""
from .assemble import assemble, check_consistency
from .io_yaml import load_request
from .rules import load_ruleset
from .validate import validate_pack

__all__ = [
    "assemble",
    "check_consistency",
    "load_request",
    "load_ruleset",
    "validate_pack",
]

__version__ = "0.1.0"
