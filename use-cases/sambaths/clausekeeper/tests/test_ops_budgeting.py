import contextlib
import io

import pytest

from clausekeeper import cli, db, rechecking
from clausekeeper.superdocs import OpsFloorExceeded

from conftest import CORPUS, FIXTURES as FIXTURES_DIR, client_for, seeded  # noqa: F401,E501
from conftest import seeded_conn  # noqa: F401


def test_full_small_sample_cycle_stays_under_ten_ops(tmp_path, monkeypatch):
    root = str(tmp_path / "cycle.db")
    monkeypatch.setenv("CK_FIXTURE", str(FIXTURES_DIR / "init_link.json"))
    cli.main(["--db", root, "init", "--corpus", str(CORPUS)])
    cli.main(["--db", root, "link"])
    monkeypatch.setenv("CK_FIXTURE", str(FIXTURES_DIR / "edit_delete.json"))
    monkeypatch.setenv("CK_AUTO_APPROVE", "1")
    cli.main(["--db", root, "edit", "NM-PRO-04", "--instruction",
              "Delete the entire 'Disposition of nonconforming devices'"
              " section; disposition decisions now live only in the ERP"
              " workflow."])
    monkeypatch.setenv("CK_FIXTURE", str(FIXTURES_DIR / "events_recheck.json"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["--db", root, "recheck", "--plan"])
        plan_text = out.getvalue()
        out.seek(0)
        out.truncate(0)
        cli.main(["--db", root, "recheck"])
        recheck_text = out.getvalue()

    assert "zero billable ops" in plan_text
    conn = db.connect(root)
    total = conn.execute(
        "SELECT SUM(ops_charged) t FROM usage_log").fetchone()["t"]
    assert total <= 10
    rows = conn.execute("SELECT ops_charged FROM usage_log").fetchall()
    assert len(rows) == 8
    remaining = conn.execute(
        "SELECT MIN(monthly_remaining) m FROM usage_log").fetchone()["m"]
    assert remaining is not None and remaining > 50
    conn.close()


def test_ops_floor_aborts_mid_run(seeded_conn):
    client = client_for("ops_floor.json")
    with pytest.raises(OpsFloorExceeded):
        rechecking.run_recheck(client, seeded_conn)
    assert any(u["monthly_remaining"] == 49 for u in client.usage_log)


def test_ops_floor_recheck_exits_two(tmp_path, monkeypatch):
    root = str(tmp_path / "floor.db")
    conn = db.connect(root)
    seeded(conn)
    conn.close()
    monkeypatch.setenv("CK_FIXTURE", str(FIXTURES_DIR / "ops_floor.json"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as excinfo:
        cli.main(["--db", root, "recheck"])
    assert excinfo.value.code == 2
    assert "STOPPED:" in out.getvalue()
