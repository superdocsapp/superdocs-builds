"""Shared test fixtures for Build A sidecar tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure offline mode — tests never hit the real API
os.environ["SUPERDOCS_API_KEY"] = "sk_test_offline_key_placeholder"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pre_edit_html() -> str:
    return """<html><body>
<p id="p1">This is the first paragraph.</p>
<p id="p2">This is the second paragraph.</p>
<p id="p3">This is the third paragraph.</p>
</body></html>"""


@pytest.fixture
def sample_post_edit_html() -> str:
    return """<html><body>
<p id="p1">This is the first paragraph.</p>
<p id="p2">This paragraph has been modified.</p>
<p id="p3">This is the third paragraph.</p>
<p id="p4">This is a new paragraph.</p>
</body></html>"""


@pytest.fixture
def sample_empty_html() -> str:
    return "<html><body></body></html>"
