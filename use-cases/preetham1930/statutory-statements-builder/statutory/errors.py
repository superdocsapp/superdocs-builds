"""Every failure this app can have, and the message it must carry.

Hard rule 13's argument, applied to a document: a bare failure tells the
reviewer something is wrong but not what to do about it. Every error below names
what could not be done and where we looked.

Non-ASCII characters are kept out of these messages on purpose: they are read in
a terminal, and Windows consoles mangled exactly the message that carried Phase
1's thesis (PROGRESS.md 2026-08-08, Assumption 19).
"""

from __future__ import annotations


class StatutoryError(Exception):
    """Base for everything raised by this package."""


class CitationDriftError(StatutoryError):
    """A citation no longer holds the literal it was created for."""


class UnaccountedFigureError(StatutoryError):
    """A money token reached a rendered body without resolving to a source."""


class ComparativeMismatchError(StatutoryError):
    """The ledger's prior-year column and the signed prior-year set disagree."""


class TieBreakError(StatutoryError):
    """A statement did not add up, or a note did not tie to its caption."""


class CrossReferenceError(StatutoryError):
    """A cross-reference does not resolve to a heading that exists."""


class ChecklistDriftError(StatutoryError):
    """A checklist item names a note the final document does not have."""


class UnknownConditionError(StatutoryError):
    """A checklist trigger could not be parsed. Never read as 'not required'."""


class UnknownAccountError(StatutoryError):
    """A trigger names an account the ledger does not have."""


class UnknownEventError(StatutoryError):
    """A trigger names an event no detector defines."""


class PlanRefusedError(StatutoryError):
    """An edit plan step broke one of the wire rules before it was sent."""


class EditNotAppliedError(StatutoryError):
    """The target chunk came back unchanged."""


class EditAppliedWrongError(StatutoryError):
    """The target chunk changed, but not to the bytes we computed."""


class CollateralDamageError(StatutoryError):
    """A chunk we did not target moved, appeared or vanished."""


class DecisionAlreadyRecordedError(StatutoryError):
    """A second decision on an item that already has one, without supersede."""


class NotConfiguredError(StatutoryError):
    """A live call was attempted with no SUPERDOCS_API_KEY set."""
