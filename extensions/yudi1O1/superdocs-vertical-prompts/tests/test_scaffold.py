"""Proves the scaffolder actually produces a loadable, structurally valid pack
— not just that it writes a file. This is the automated half of "the
pack-building template genuinely produces a working pack for a second
vertical, demonstrated" (the other half is packs/real_estate/pack.yaml itself,
which really was generated this way — see its header comment and the README)."""
import os

from vertical_prompts.pack_spec import load_pack
from vertical_prompts.scaffold import build_pack_dict, main as scaffold_main


def test_build_pack_dict_produces_structurally_complete_pack():
    d = build_pack_dict(
        pack_id="healthcare",
        display_name="Healthcare Pack",
        description="desc",
        vertical="Healthcare",
        command_flags=["prior_auth:Draft a prior authorization letter", "denial_appeal:Draft a denial appeal"],
    )
    assert d["pack_id"] == "healthcare"
    assert len(d["commands"]) == 2
    ids = {c["id"] for c in d["commands"]}
    assert ids == {"prior_auth", "denial_appeal"}
    for c in d["commands"]:
        assert c["approval_mode"] in ("ask_every_time", "approve_all")
        assert c["arguments"]
        assert "{" in c["instruction_template"]  # has a placeholder to fill in


def test_scaffolded_pack_loads_through_the_same_loader_real_packs_use(tmp_path):
    out_path = tmp_path / "generated" / "pack.yaml"
    exit_code = scaffold_main([
        "--pack-id", "healthcare",
        "--display-name", "Healthcare Pack",
        "--description", "desc",
        "--vertical", "Healthcare",
        "--command", "prior_auth:Draft a prior authorization letter",
        "--out", str(out_path),
    ])
    assert exit_code == 0
    assert out_path.exists()

    # A freshly scaffolded pack has a placeholder instruction_template that
    # references {context} and declares 'context' as an argument, so it loads
    # cleanly (structurally valid) even before a human fills in real content.
    pack = load_pack(str(out_path))
    assert pack.pack_id == "healthcare"
    assert len(pack.commands) == 1
    assert pack.commands[0].id == "prior_auth"


def test_scaffold_rejects_malformed_command_flag(tmp_path):
    out_path = tmp_path / "pack.yaml"
    try:
        scaffold_main([
            "--pack-id", "x", "--display-name", "X", "--description", "d", "--vertical", "V",
            "--command", "missing_colon_and_title",
            "--out", str(out_path),
        ])
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code != 0
