import os

import pytest
import yaml

from vertical_prompts.pack_spec import (
    ArgumentError,
    ArgumentSpec,
    CommandSpec,
    PackSpecError,
    load_pack,
    render_full_prompt,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGAL_PACK_PATH = os.path.join(ROOT, "packs", "legal", "pack.yaml")
REAL_ESTATE_PACK_PATH = os.path.join(ROOT, "packs", "real_estate", "pack.yaml")


def _write_pack(tmp_path, data: dict) -> str:
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def _minimal_pack_dict(**command_overrides) -> dict:
    command = {
        "id": "do_thing",
        "title": "Do the thing",
        "description": "Does the thing.",
        "approval_mode": "ask_every_time",
        "instruction_template": "Do the thing with {x}.",
        "arguments": [{"name": "x", "description": "the thing", "required": True}],
    }
    command.update(command_overrides)
    return {
        "pack_id": "test_pack",
        "display_name": "Test Pack",
        "description": "A test pack.",
        "vertical": "Testing",
        "commands": [command],
    }


# --- real packs load cleanly -------------------------------------------------

def test_legal_pack_loads():
    pack = load_pack(LEGAL_PACK_PATH)
    assert pack.pack_id == "legal"
    assert {c.id for c in pack.commands} == {
        "redline", "fallback_clause", "draft_from_playbook", "obligation_summary",
    }


def test_real_estate_pack_loads():
    pack = load_pack(REAL_ESTATE_PACK_PATH)
    assert pack.pack_id == "real_estate"
    assert {c.id for c in pack.commands} == {"draft_disclosure", "compare_addendum", "closing_checklist"}


# --- structural validation (author-time errors) ------------------------------

def test_undeclared_placeholder_is_rejected(tmp_path):
    data = _minimal_pack_dict(instruction_template="Do the thing with {x} and {y}.")  # y undeclared
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError, match="y"):
        load_pack(path)


def test_invalid_approval_mode_is_rejected(tmp_path):
    data = _minimal_pack_dict(approval_mode="auto_pilot")
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError, match="approval_mode"):
        load_pack(path)


def test_invalid_export_format_is_rejected(tmp_path):
    data = _minimal_pack_dict()
    data["commands"][0]["export"] = {"format": "excel"}
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError, match="export.format"):
        load_pack(path)


def test_duplicate_command_ids_rejected(tmp_path):
    data = _minimal_pack_dict()
    data["commands"].append(dict(data["commands"][0]))
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError, match="duplicate"):
        load_pack(path)


def test_non_snake_case_command_id_rejected(tmp_path):
    data = _minimal_pack_dict(id="DoTheThing")
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError):
        load_pack(path)


def test_empty_commands_rejected(tmp_path):
    data = _minimal_pack_dict()
    data["commands"] = []
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError, match="no commands"):
        load_pack(path)


def test_missing_top_level_field_rejected(tmp_path):
    data = _minimal_pack_dict()
    del data["vertical"]
    path = _write_pack(tmp_path, data)
    with pytest.raises(PackSpecError, match="vertical"):
        load_pack(path)


# --- argument rendering (invocation-time errors) ------------------------------

def _command(**overrides) -> CommandSpec:
    defaults = dict(
        id="redline",
        title="Redline",
        description="desc",
        approval_mode="ask_every_time",
        instruction_template="Redline {doc} focusing on {focus}.",
        arguments=[
            ArgumentSpec(name="doc", description="the document", required=True),
            ArgumentSpec(name="focus", description="what to focus on", required=False, default="everything"),
        ],
    )
    defaults.update(overrides)
    return CommandSpec(**defaults)


def test_render_fills_in_provided_arguments():
    cmd = _command()
    text = cmd.render({"doc": "the MSA", "focus": "liability"})
    assert text == "Redline the MSA focusing on liability."


def test_render_uses_default_for_omitted_optional_argument():
    cmd = _command()
    text = cmd.render({"doc": "the MSA"})
    assert "everything" in text


def test_render_missing_required_argument_raises_with_field_name_and_description():
    cmd = _command()
    with pytest.raises(ArgumentError) as exc_info:
        cmd.render({})
    message = str(exc_info.value)
    assert "doc" in message
    assert "the document" in message  # the argument's own description, not a generic message


def test_render_rejects_unknown_argument_name():
    cmd = _command()
    with pytest.raises(ArgumentError, match="unrecognized"):
        cmd.render({"doc": "the MSA", "nonexistent": "x"})


def test_render_never_invents_a_value_for_missing_required_field():
    """Mirrors the FMEA build's core rule, applied to prompt arguments: a
    required argument the user didn't supply must stop the render, never
    silently substitute empty string or a guess."""
    cmd = _command(instruction_template="Redline {doc}.", arguments=[ArgumentSpec(name="doc", description="the doc", required=True)])
    with pytest.raises(ArgumentError):
        cmd.render({})


# --- full prompt rendering (approval-mode guidance) ---------------------------

def test_ask_every_time_guidance_forbids_auto_approval():
    cmd = _command(approval_mode="ask_every_time")
    text = render_full_prompt(cmd, {"doc": "the MSA", "focus": "liability"})
    assert "chat_async" in text
    assert "Do not auto-approve" in text or "do not auto-approve" in text.lower()


def test_approve_all_guidance_differs_from_ask_every_time():
    ask_cmd = _command(approval_mode="ask_every_time")
    approve_cmd = _command(approval_mode="approve_all")
    ask_text = render_full_prompt(ask_cmd, {"doc": "x"})
    approve_text = render_full_prompt(approve_cmd, {"doc": "x"})
    assert ask_text != approve_text
    assert "approval_mode=\"approve_all\"" in approve_text
    assert "approval_mode=\"ask_every_time\"" in ask_text


def test_template_backed_command_tells_the_assistant_to_use_saved_templates():
    """The `templates` surface: a command marked use_saved must route the
    assistant through list_user_templates rather than generic boilerplate."""
    pack = load_pack(LEGAL_PACK_PATH)
    cmd = pack.get_command("draft_from_playbook")
    assert cmd.templates.use_saved is True
    text = render_full_prompt(cmd, {
        "document_type": "a mutual NDA",
        "counterparty": "Northwind Logistics GmbH",
        "key_terms": "2-year term, Delaware law",
    })
    assert "list_user_templates" in text
    assert "upload_template_base64" in text


def test_template_backed_command_forbids_inventing_house_language():
    """Same 'never invent' rule as the FMEA build, applied to house paper: no
    saved template means say so, not fabricate the organisation's standard."""
    pack = load_pack(LEGAL_PACK_PATH)
    cmd = pack.get_command("draft_from_playbook")
    text = render_full_prompt(cmd, {"document_type": "an NDA", "counterparty": "X", "key_terms": "y"})
    assert "do NOT invent house-standard language" in text


def test_commands_without_templates_get_no_template_guidance():
    """Guidance is opt-in per command — a redline works on the open document and
    must not be sent hunting through the template library."""
    pack = load_pack(LEGAL_PACK_PATH)
    cmd = pack.get_command("redline")
    assert cmd.templates.use_saved is False
    text = render_full_prompt(cmd, {
        "contract_description": "the MSA",
        "focus_areas": "liability",
        "negotiating_position": "mutual",
    })
    assert "list_user_templates" not in text


def test_export_settings_are_embedded_in_rendered_prompt():
    from vertical_prompts.pack_spec import ExportSpec

    cmd = _command()
    cmd.export = ExportSpec(format="pdf", options={"filename": "custom-name"})
    text = render_full_prompt(cmd, {"doc": "x"})
    assert 'format="pdf"' in text
    assert "custom-name" in text
