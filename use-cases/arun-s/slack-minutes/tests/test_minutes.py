import sys, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from minutes import structure, minutes_html, export_minutes
from slack import Slack
from superdocs_min import SuperDocs

MSGS = json.load(open(ROOT / "sample_thread.json"))["messages"]

def test_structures_decisions_actions_attendees():
    s = structure(MSGS)
    assert set(s["attendees"]) == {"arun", "meera", "omkar"}
    assert any("keep pricing unchanged" in d["text"] for d in s["decisions"])
    assert any("Aug 20" in d["text"] for d in s["decisions"])
    owners = {a["owner"] for a in s["actions"]}
    assert "arun" in owners and "meera" in owners          # @mention owners captured

def test_minutes_html_has_sections():
    html = minutes_html(structure(MSGS), "Q3")
    assert "<h2>Decisions</h2>" in html and "<h2>Action items</h2>" in html

def _fake_slack(method, url, headers, params):
    return 200, json.dumps({"ok": True, "messages": MSGS})
def _fake_sd(method, url, headers, body):
    if url.endswith("/chat/async"): return 200, '{"job_id":"j","status":"completed"}'
    return 200, "PK\x03\x04 docx"

def test_full_pipeline_slack_to_export():
    res = export_minutes(Slack("t", transport=_fake_slack), SuperDocs("k", transport=_fake_sd), "C1", "1.0")
    assert res["structured"]["decisions"] and len(res["docx"]) > 0
