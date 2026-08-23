"""8A — the shell: does Word have something to load, and does it say what it is?"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app
from service.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.xml"
OFFICE_NS = "{http://schemas.microsoft.com/office/appforoffice/1.1}"


def client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path, **overrides)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def test_health_says_which_tiers_can_actually_run(tmp_path: Path) -> None:
    """The difference between a clean document and a switched-off detector.

    With no model key, a scan finds only what patterns find — and a pane that
    reported "no candidates" without saying so would be telling a records
    officer their document is clean when nobody looked for half of it.
    """
    body = client(tmp_path).get("/health").json()

    assert body["status"] == "ok"
    assert body["tiers"] == ["patterns"], "no key means tier 3 did not run"
    assert body["degraded"] is True
    assert any("OPENAI_API_KEY" in line for line in body["missing_configuration"])
    assert any("SUPERDOCS_API_KEY" in line for line in body["missing_configuration"])


def test_health_states_the_boundary(tmp_path: Path) -> None:
    """The honesty note is a requirement, so it is asserted like one."""
    body = client(tmp_path).get("/health").json()

    # "tracked deletions", not "tracked changes". An insertion's text is
    # ordinary visible body text and is reported as such; a deletion is the one
    # that is invisible in Word and still in the file. Claiming both under one
    # word would overstate what is special about the coverage.
    assert "tracked deletions" in body["covers"]
    for part in ("headers", "footers", "footnotes", "comments"):
        assert part in body["covers"]
    assert "docProps" in body["does_not_cover"]
    assert "never modified" in body["does_not_cover"]


def test_a_key_switches_the_llm_tier_on(tmp_path: Path) -> None:
    body = client(tmp_path, openai_api_key="sk-test").get("/health").json()

    assert body["tiers"] == ["patterns", "llm"]


def test_the_taskpane_route_answers_even_before_the_ui_is_built(tmp_path: Path) -> None:
    """A 404 inside a task pane is a blank white rectangle with no explanation.

    Word gives the user no error and no clue which of the setup steps was
    missed, so the unbuilt pane says so in the pane.
    """
    response = client(tmp_path).get("/taskpane.html")

    assert response.status_code == 200
    assert "Redaction Pane" in response.text


def test_a_mistyped_api_path_is_a_404_not_the_pane(tmp_path: Path) -> None:
    """Serving index.html for every unknown path turns "no such route" into a
    200 and an empty screen."""
    assert client(tmp_path).get("/scna").status_code == 404


class TestManifest:
    """What Word reads. Every one of these is a rule Office enforces, and
    breaking any of them makes the add-in silently fail to appear."""

    root = ET.parse(MANIFEST).getroot()

    def test_it_is_a_task_pane_app(self) -> None:
        assert self.root.tag == f"{OFFICE_NS}OfficeApp"
        assert self.root.get("{http://www.w3.org/2001/XMLSchema-instance}type") == "TaskPaneApp"

    def test_the_source_location_is_https(self) -> None:
        """Office refuses an http:// task pane even on localhost. This is the
        reason the certificate step exists at all."""
        source = self.root.find(f"{OFFICE_NS}DefaultSettings/{OFFICE_NS}SourceLocation")
        assert source is not None
        assert source.get("DefaultValue", "").startswith("https://")

    def test_every_url_it_declares_is_https(self) -> None:
        for element in self.root.iter():
            value = element.get("DefaultValue", "")
            if value.startswith("http"):
                assert value.startswith("https://"), f"{element.tag} is not https"

    def test_the_version_is_at_least_one(self) -> None:
        """Office rejects anything below 1.0.0.0 — its own validator calls it
        "Manifest Version Too Low", and the sideload just does not appear."""
        version = self.root.findtext(f"{OFFICE_NS}Version", "")
        assert tuple(int(part) for part in version.split(".")) >= (1, 0, 0, 0)

    def test_it_asks_for_write_permission_and_says_why(self) -> None:
        assert self.root.findtext(f"{OFFICE_NS}Permissions") == "ReadWriteDocument"

    def test_the_app_domain_matches_the_source_location(self) -> None:
        """A pane that navigates outside its declared domains is blocked by
        Office, and the failure looks like a blank pane."""
        source = self.root.find(f"{OFFICE_NS}DefaultSettings/{OFFICE_NS}SourceLocation")
        origin = "/".join((source.get("DefaultValue") or "").split("/")[:3])
        domains = [node.text for node in self.root.iter(f"{OFFICE_NS}AppDomain")]
        assert origin in domains
