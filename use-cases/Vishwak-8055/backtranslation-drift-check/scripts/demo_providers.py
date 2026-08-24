"""Builds the FixtureProviders used by the flagship and second-document demos.

The flagship fixture's back-translations and semantic overrides both live in
fixtures/flagship/back_translations.json (structured format — see
FixtureProvider.from_json_file's docstring). This module is now a thin
wrapper; it exists so tests and demo scripts have one obvious place to get a
correctly configured provider, but `drift-check run --provider fixture
--fixture-file fixtures/flagship/back_translations.json` reproduces the same
result on its own, including the semantic-only Section 12 finding — the
overrides are no longer Python-only.
"""

from __future__ import annotations

from pathlib import Path

from drift_check.providers.fixture import FixtureProvider

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def build_flagship_provider() -> FixtureProvider:
    return FixtureProvider.from_json_file(FIXTURES_DIR / "flagship" / "back_translations.json")


def build_second_doc_provider() -> FixtureProvider:
    return FixtureProvider.from_json_file(FIXTURES_DIR / "second_doc" / "back_translations.json")
