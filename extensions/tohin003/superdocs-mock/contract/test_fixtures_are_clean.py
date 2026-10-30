"""Every committed fixture must be safe to publish, and honest about what it is.

These run with no key and no network. They are the gate that lets this repository be
public: fixtures recorded against a live service are exactly the artifact most likely to
carry a credential by accident, so the check is mechanical and it runs on every push.

Deliberately independent of the scrubber where it can be. A scrubber and a test that
share all their logic only prove the logic is self-consistent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sdmock.cassette import Cassette, load_all
from sdmock.scrub import audit

ROOT = Path(__file__).resolve().parent.parent
CASSETTES = ROOT / "cassettes"
CORPUS = ROOT / "corpus"

CASSETTE_FILES = sorted(CASSETTES.glob("*.json"))


def ids(paths: list[Path]) -> list[str]:
    return [p.stem for p in paths]


@pytest.mark.parametrize("path", CASSETTE_FILES, ids=ids(CASSETTE_FILES))
def test_cassette_carries_no_secret(path: Path) -> None:
    """No API key, bearer token, personal address or signed URL survives on disk."""
    problems = audit(path.read_text(encoding="utf-8"))
    assert not problems, f"{path.name}: " + "; ".join(problems)


@pytest.mark.parametrize("path", CASSETTE_FILES, ids=ids(CASSETTE_FILES))
def test_cassette_loads_and_is_self_describing(path: Path) -> None:
    """A cassette must load under the current schema and say what it is."""
    cassette = Cassette.load(path)
    assert cassette.scenario == path.stem, "scenario id must match the filename"
    assert cassette.description.strip(), "a scenario with no description is unusable"
    assert cassette.interactions, "a cassette with no interactions replays nothing"
    assert cassette.covers, "a scenario that exercises no B-ID is untested by design"
    assert cassette.spec_pin, "a cassette must name the spec it was captured against"


@pytest.mark.parametrize("path", CASSETTE_FILES, ids=ids(CASSETTE_FILES))
def test_synthesised_cassettes_declare_themselves(path: Path) -> None:
    """A reconstruction must never be able to pass as a recording.

    Recorded cassettes name the server they came from; synthesised ones carry a note
    explaining why they could not be recorded. Neither is allowed to be silent.
    """
    cassette = Cassette.load(path)
    if cassette.synthesised:
        assert cassette.synthesis_note.strip(), (
            f"{path.name} is synthesised but does not say why it could not be recorded"
        )
    else:
        assert cassette.recorded_against.get("server"), (
            f"{path.name} claims to be a recording but names no server"
        )


@pytest.mark.parametrize("path", CASSETTE_FILES, ids=ids(CASSETTE_FILES))
def test_cassette_is_canonically_serialised(path: Path) -> None:
    """On-disk form is canonical, so a re-recording diffs only where behaviour moved."""
    from sdmock.cassette import dumps

    raw = path.read_text(encoding="utf-8")
    expected = dumps(json.loads(raw)) + "\n"
    assert raw == expected, (
        f"{path.name} is not canonically serialised -- re-save it through "
        "Cassette.save so diffs stay meaningful"
    )


def test_scenario_ids_are_unique() -> None:
    """Two cassettes claiming one scenario id would make replay ambiguous."""
    assert load_all(CASSETTES), "no cassettes found"


# --------------------------------------------------------------------------- corpus


def test_corpus_contains_no_real_addresses() -> None:
    """The corpus is fabricated; a real address in it would end up in a cassette."""
    allowed = {"hello@superdocs.app", "user@example.com", "redacted@example.com"}
    pattern = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
    offenders: list[str] = []
    for path in sorted(CORPUS.iterdir()):
        if path.suffix in {".docx", ".odt", ".doc"} or path.is_dir():
            continue  # binary containers; covered by the cassette audit downstream
        for match in pattern.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            if match.group(0).lower() not in allowed:
                offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, "real-looking addresses in the corpus: " + "; ".join(offenders)


def test_corpus_documents_declare_themselves_synthetic() -> None:
    """Each text corpus document says on its face that it is not real.

    If a fixture ever escapes into someone's test output, it should announce itself
    rather than look like a leaked contract.
    """
    for name in ("q1-operations-review.md",
                 "large-consignment-register.html",
                 "oversize-consignment-register.html"):
        text = (CORPUS / name).read_text(encoding="utf-8")[:4000]
        assert "Synthetic sample document" in text, (
            f"{name} does not declare itself synthetic in its opening"
        )
