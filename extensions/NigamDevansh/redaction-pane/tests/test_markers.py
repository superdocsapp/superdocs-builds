"""Typed markers — `[CREDIT CARD REDACTED]`, not `[REDACTED]`.

The point of the type is that the released document stays reviewable. These
tests pin the two halves of that: tier 1's exact kinds map to exact markers, and
tier 3's free-text kinds are **normalised or dropped to the category** — never
turned into a marker on the strength of a model's phrasing.
"""

from __future__ import annotations

import pytest

from service.markers import marker


@pytest.mark.parametrize(
    ("category", "kind", "expected"),
    [
        # Tier 1: the detector matched a shape, so the marker is exact.
        ("account", "credit_card", "[CREDIT CARD REDACTED]"),
        ("personal", "ssn", "[SSN REDACTED]"),
        ("account", "account_number", "[ACCOUNT NUMBER REDACTED]"),
        ("personal", "email", "[EMAIL REDACTED]"),
        ("personal", "phone", "[PHONE NUMBER REDACTED]"),
        ("health", "medical_record", "[MEDICAL RECORD REDACTED]"),
        ("personal", "passport", "[PASSPORT NUMBER REDACTED]"),
        # Tier 3 and tier 2: whatever words the model or the model's label used.
        ("personal", "person's name", "[NAME REDACTED]"),
        # Tier 2's raw labels — the same marker as tier 3's phrasing for the
        # same thing, so the document does not record which detector found it.
        ("personal", "person", "[NAME REDACTED]"),
        ("personal", "address", "[ADDRESS REDACTED]"),
        ("personal", "home address", "[ADDRESS REDACTED]"),
        ("personal", "date of birth", "[DATE OF BIRTH REDACTED]"),
        ("personal", "Routing Number", "[ROUTING NUMBER REDACTED]"),
        ("health", "healthcare referral", "[HEALTH DATA REDACTED]"),
        ("health", "diagnosis", "[HEALTH DATA REDACTED]"),
        ("privileged", "litigation strategy", "[LEGAL STRATEGY REDACTED]"),
        ("privileged", "settlement position", "[SETTLEMENT POSITION REDACTED]"),
    ],
)
def test_the_marker_says_what_kind_of_thing_was_removed(
    category: str, kind: str, expected: str
) -> None:
    assert marker(category, kind) == expected


class TestUnknownKinds:
    """A model can return any string it likes for `kind`. None of them become a
    marker unless this file recognises them."""

    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            ("personal", "[PERSONAL DATA REDACTED]"),
            ("health", "[HEALTH DATA REDACTED]"),
            ("account", "[ACCOUNT DETAIL REDACTED]"),
            ("privileged", "[PRIVILEGED CONTENT REDACTED]"),
        ],
    )
    def test_an_unrecognised_kind_falls_back_to_the_category(
        self, category: str, expected: str
    ) -> None:
        assert marker(category, "some phrasing nobody anticipated") == expected

    def test_an_empty_kind_still_produces_a_marker(self) -> None:
        """Every candidate has a category, so every candidate has a marker.
        There is no path to writing an empty string into a document."""
        assert marker("personal", "") == "[PERSONAL DATA REDACTED]"

    def test_a_kind_is_never_interpolated_verbatim(self) -> None:
        """The kind is untrusted: it can come straight from a model. Putting it
        in the document unchecked would let a document choose what its own
        redaction marker says."""
        hostile = "</w:t><w:br/>ATTACKER"

        assert marker("personal", hostile) == "[PERSONAL DATA REDACTED]"
        assert "ATTACKER" not in marker("personal", hostile)


def test_every_marker_is_recognisable_as_one() -> None:
    """A reader scanning a printed page has to see that something was taken
    out. That is what the brackets and the word are for."""
    for category in ("personal", "health", "account", "privileged"):
        result = marker(category, "anything")
        assert result.startswith("[")
        assert result.endswith(" REDACTED]")
