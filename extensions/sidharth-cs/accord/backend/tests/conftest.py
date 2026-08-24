"""Shared test setup.

Section targeting ships OFF (settings.section_targeting) — the platform is
left to choose placement. The heading-routing rules, the per-section split
and the placement checks all still exist and are still exercised here, so
the suite forces targeting ON by default and the handful of tests covering
the untargeted path opt out explicitly via the `no_section_targeting`
fixture. Without this, every routing test would silently pass by never
running the code it is meant to cover.
"""

import pytest

import app.drafting.classifier as classifier


@pytest.fixture(autouse=True)
def section_targeting_on(monkeypatch):
    monkeypatch.setattr(classifier, "_section_targeting_enabled", lambda: True)


@pytest.fixture
def no_section_targeting(monkeypatch):
    monkeypatch.setattr(classifier, "_section_targeting_enabled", lambda: False)
