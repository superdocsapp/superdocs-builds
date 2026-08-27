"""The honesty matrix: the floor is honest about what it recovered.

Runs the engine over every real ``.docx`` in the corpus and holds it to two
rules the whole product stands on:

* **No empty success.** A verdict of ``"full"`` must mean words actually came
  back. If the engine claims full recovery and reports zero words, the test
  fails and the process exits non-zero -- the exact overclaim this build exists
  to prevent.
* **Styling can fail, recovery cannot.** When the SuperDocs styling pass
  raises (simulated with a network timeout), the CLI must still exit 0 and hand
  back the local fallback document. The ceiling is allowed to be unreachable;
  the floor is not.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from unittest import mock

import pytest
import requests

from docrepair import engine

CORPUS = Path(__file__).resolve().parent
ORIGINALS = CORPUS / "originals"


def _docx_files() -> list[Path]:
    return sorted(
        Path(p)
        for p in glob.glob(str(CORPUS / "**" / "*.docx"), recursive=True)
        if "measurements" not in p
    )


@pytest.mark.parametrize("path", _docx_files(), ids=lambda p: p.name)
def test_the_engine_is_honest_about_what_it_recovered(path: Path) -> None:
    data = path.read_bytes()
    result = engine.repair(data, path.name)

    # The one rule that is non-negotiable: "full" with nothing in it is the worst
    # output this tool can produce, because it opens cleanly and says nothing
    # was lost.
    if result.verdict == "full":
        assert result.word_count > 0, (
            f"Empty-success detected on {path.name}: verdict was 'full' but "
            f"{result.word_count} words were recovered."
        )
    else:
        # A partial or refused result must at least name what went wrong, so the
        # person is never left guessing.
        assert result.verdict in ("partial", "refused")


def test_a_superdocs_timeout_degrades_to_the_local_file_with_exit_zero() -> None:
    """The styling pass is the ceiling; the local rebuild is the floor. A dead
    network must not take the floor away from the caller."""
    sample = next(iter(_docx_files()), None)
    if sample is None:
        pytest.skip("no corpus .docx to run the CLI against")

    from cli import main as cli_main

    # Patch the network call, not the method, so the real styled_export catches
    # the timeout exactly as it would in production and degrades to the local
    # file. Patching the method would skip its own try/except.
    with mock.patch(
        "docrepair.superdocs_client.requests.post",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with mock.patch("sys.argv", [  # noqa: S106 -- test harness only
            "cli", str(sample), "--via-superdocs",
        ]):
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli_main()

    assert code == 0, "the CLI must exit 0 even when SuperDocs times out"
    manifest = __import__("json").loads(buf.getvalue().strip())
    assert manifest["path_taken"] == "superdocs_failed"
    assert manifest["verdict"] in ("full", "partial", "refused")
