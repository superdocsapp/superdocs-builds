"""Every failure this app can have, and the message it must carry.

Hard rule 13's argument, applied to a document: a bare failure tells the
reviewer something is wrong but not what to do about it. Every error below names
what could not be done and where we looked.

Non-ASCII characters are kept out of these messages on purpose: they are read in
a terminal, and Windows consoles mangled exactly the message that carried Phase
1's thesis (PROGRESS.md 2026-08-08, Assumption 19).
"""

from __future__ import annotations


class PoaError(Exception):
    """Base for everything raised by this package."""


# -- the intake ------------------------------------------------------------


class UnknownPowerError(PoaError):
    """The intake names a power id the catalogue does not have."""


class UnknownPoaTypeError(PoaError):
    """The intake names a POA type the library does not define."""


class UnknownJurisdictionError(PoaError):
    """The intake names a jurisdiction the library does not define."""


class IncompleteIntakeError(PoaError):
    """The intake cannot support a draft - a limited POA with no stated limit,
    a missing successor agent, a party with no name."""


# -- the library -----------------------------------------------------------


class UnknownConditionError(PoaError):
    """A clause condition could not be parsed. Never read as 'does not apply'."""


class UnresolvedPlaceholderError(PoaError):
    """A clause placeholder has no resolver. Never left in and never emptied."""


class LibraryRefusedError(PoaError):
    """A library row is not fit to be used - a jurisdiction row that asserts an
    execution requirement instead of deferring it, a duplicate clause id."""


class CrossReferenceError(PoaError):
    """A clause reference does not resolve to a clause the draft has."""


# -- the legal-adjacency guards -------------------------------------------


class ForbiddenPhraseError(PoaError):
    """The draft says something this product has no standing to say."""


class NoticeMissingError(PoaError):
    """A required notice is not present in the document."""


class NoticeAlteredError(PoaError):
    """A required notice is present but not verbatim."""


class ExportRefusedError(PoaError):
    """An export was attempted without a receipt from the notice gate."""


# -- the wire --------------------------------------------------------------


class PlanRefusedError(PoaError):
    """An edit plan step broke one of the wire rules before it was sent."""


class DecisionAlreadyRecordedError(PoaError):
    """A second decision on an item that already has one, without supersede."""


class NotConfiguredError(PoaError):
    """A live call was attempted with no SUPERDOCS_API_KEY set."""
