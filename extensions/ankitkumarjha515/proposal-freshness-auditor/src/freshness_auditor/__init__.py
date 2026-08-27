"""Proposal Boilerplate Freshness Auditor.

Holds canonical organisational facts (the "ledger") and a registry of the
documents to check them against (the "corpus"). This package (T1) only
provides the data model and loaders; the detection engine (T2), the review
flow (T3), and any SuperDocs API integration (T4) are out of scope here.
"""

from .ledger import (
    Fact,
    FactLedger,
    FactLedgerError,
    DuplicateFactIdError,
    InvalidFactKindError,
    InvalidDateError,
    StalePriorValueError,
    PriorValueDateOrderError,
    EmptySubjectError,
    EmptySynonymsError,
    FactNotFoundError,
    PriorValue,
)
from .corpus import (
    Corpus,
    CorpusError,
    Document,
    DuplicateDocumentIdError,
    InvalidDocumentRoleError,
    MissingDocumentFileError,
    DocumentNotFoundError,
)

__all__ = [
    "Fact",
    "FactLedger",
    "FactLedgerError",
    "DuplicateFactIdError",
    "InvalidFactKindError",
    "InvalidDateError",
    "StalePriorValueError",
    "PriorValueDateOrderError",
    "EmptySubjectError",
    "EmptySynonymsError",
    "FactNotFoundError",
    "PriorValue",
    "Corpus",
    "CorpusError",
    "Document",
    "DuplicateDocumentIdError",
    "InvalidDocumentRoleError",
    "MissingDocumentFileError",
    "DocumentNotFoundError",
]
