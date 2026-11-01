import json

from soc2_index.paths import project_root
from soc2_index.superdocs.hitl import (
    awaiting_kind,
    encode_approve_all,
    encode_approve_one,
    is_continue_prompt,
    maybe_json,
    pending_changes,
)

FX = project_root() / "fixtures/superdocs"


def test_stringified_batch():
    raw = json.loads((FX / "proposed_change_batch_stringified.json").read_text())
    parsed = maybe_json(raw["content"])
    assert parsed["changes"][0]["change_id"] == "ch_1"


def test_continue_vs_hitl():
    hitl = json.loads((FX / "job_awaiting.json").read_text())
    cont = json.loads((FX / "job_awaiting_continue.json").read_text())
    assert not is_continue_prompt(hitl)
    assert is_continue_prompt(cont)
    assert awaiting_kind(cont) == "continue_prompt"
    assert pending_changes(hitl)[0]["change_id"] == "ch_1"


def test_approve_bodies():
    one = encode_approve_one("job", "ch_1", True)
    assert one == {"job_id": "job", "change_id": "ch_1", "approved": True}
    batch = encode_approve_all(
        "job",
        [
            {"change_id": "ch_1", "document_id": "idx"},
            {"change_id": "ch_2", "document_id": "tab"},
        ],
        index_document_id="idx",
    )
    assert batch["approved"] is True
    assert batch["changes"][0]["approved"] is True
    assert batch["changes"][1]["approved"] is False


def test_approve_200_empty():
    body = json.loads((FX / "approve_200.json").read_text())
    assert body == {}
