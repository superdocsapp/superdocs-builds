"""Pack spec: the data model, loader, and validator for a vertical workflow-prompt
pack (a YAML file describing a set of MCP prompts / slash commands).

This module has no MCP dependency — `server.py` is the only place that touches
the `mcp` package. That split is what makes `test_pack_spec.py` fast, offline,
and independent of which MCP SDK version is installed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_APPROVAL_MODES = {"approve_all", "ask_every_time"}
VALID_EXPORT_FORMATS = {"docx", "pdf", "html", "markdown", "txt"}

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class PackSpecError(ValueError):
    """Raised for structural problems in a pack.yaml itself (author-time errors)."""


class ArgumentError(ValueError):
    """Raised for a bad/missing argument at prompt-invocation time (user-time errors).
    Carries a message written to be shown directly to whoever typed the slash command."""


@dataclass
class ArgumentSpec:
    name: str
    description: str
    required: bool = True
    default: str | None = None


@dataclass
class ExportSpec:
    format: str = "docx"
    options: dict = field(default_factory=dict)


@dataclass
class TemplateSpec:
    """Whether this command should draft from the user's own saved SuperDocs
    templates (the `templates` surface: list_user_templates / upload_template_base64).

    Verticals run on house paper — a legal team's own NDA, a supplier's own
    8D form. `use_saved: true` tells the assistant to find that template first
    rather than inventing house language from scratch."""
    use_saved: bool = False
    hint: str = ""


@dataclass
class CommandSpec:
    id: str
    title: str
    description: str
    approval_mode: str
    instruction_template: str
    arguments: list[ArgumentSpec] = field(default_factory=list)
    export: ExportSpec = field(default_factory=ExportSpec)
    templates: TemplateSpec = field(default_factory=TemplateSpec)
    superdocs_tool: str = "chat_async"  # which SuperDocs MCP tool the rendered instruction tells the assistant to call

    def argument_names(self) -> set[str]:
        return {a.name for a in self.arguments}

    def render(self, provided: dict[str, str]) -> str:
        """Render `instruction_template` with `provided` argument values.

        Raises ArgumentError with a message fit to show the end user (not a
        traceback) for any missing required argument or unknown argument name.
        Never silently defaults a required value — same rule as the FMEA
        drafter build applies here: an argument the user didn't supply is a
        hard stop, not a guess.
        """
        known = self.argument_names()
        unknown = set(provided) - known
        if unknown:
            raise ArgumentError(
                f"/{self.id}: unrecognized argument(s) {sorted(unknown)}. "
                f"Expected one of: {sorted(known) or '(no arguments)'}."
            )

        values: dict[str, str] = {}
        missing: list[str] = []
        for arg in self.arguments:
            if arg.name in provided and provided[arg.name] not in (None, ""):
                values[arg.name] = provided[arg.name]
            elif arg.default is not None:
                values[arg.name] = arg.default
            elif arg.required:
                missing.append(arg.name)
            else:
                values[arg.name] = ""

        if missing:
            details = "; ".join(
                f"'{name}' — {next(a.description for a in self.arguments if a.name == name)}"
                for name in missing
            )
            raise ArgumentError(
                f"/{self.id} is missing {len(missing)} required argument(s): {details}"
            )

        return self.instruction_template.format(**values)


@dataclass
class PackSpec:
    pack_id: str
    display_name: str
    description: str
    vertical: str
    commands: list[CommandSpec] = field(default_factory=list)

    def get_command(self, command_id: str) -> CommandSpec | None:
        return next((c for c in self.commands if c.id == command_id), None)


def _parse_argument(raw: dict) -> ArgumentSpec:
    if "name" not in raw or "description" not in raw:
        raise PackSpecError(f"argument entry missing 'name' or 'description': {raw}")
    return ArgumentSpec(
        name=raw["name"],
        description=raw["description"],
        required=raw.get("required", True),
        default=raw.get("default"),
    )


def _parse_command(raw: dict) -> CommandSpec:
    for required_field in ("id", "title", "description", "approval_mode", "instruction_template"):
        if required_field not in raw:
            raise PackSpecError(f"command missing required field '{required_field}': {raw}")

    if raw["approval_mode"] not in VALID_APPROVAL_MODES:
        raise PackSpecError(
            f"command '{raw['id']}': approval_mode must be one of {sorted(VALID_APPROVAL_MODES)}, "
            f"got '{raw['approval_mode']}'"
        )

    export_raw = raw.get("export", {}) or {}
    export_format = export_raw.get("format", "docx")
    if export_format not in VALID_EXPORT_FORMATS:
        raise PackSpecError(
            f"command '{raw['id']}': export.format must be one of {sorted(VALID_EXPORT_FORMATS)}, "
            f"got '{export_format}'"
        )
    export = ExportSpec(format=export_format, options=export_raw.get("options", {}) or {})

    templates_raw = raw.get("templates", {}) or {}
    if not isinstance(templates_raw, dict):
        raise PackSpecError(f"command '{raw['id']}': 'templates' must be a mapping, got {type(templates_raw).__name__}")
    templates = TemplateSpec(
        use_saved=bool(templates_raw.get("use_saved", False)),
        hint=templates_raw.get("hint", "") or "",
    )

    arguments = [_parse_argument(a) for a in raw.get("arguments", []) or []]
    arg_names = {a.name for a in arguments}

    placeholders = set(_PLACEHOLDER_RE.findall(raw["instruction_template"]))
    undeclared = placeholders - arg_names
    if undeclared:
        raise PackSpecError(
            f"command '{raw['id']}': instruction_template references {sorted(undeclared)} "
            f"which {'is' if len(undeclared) == 1 else 'are'} not declared in 'arguments'."
        )

    # A declared argument the template never uses is a spec smell, not an error —
    # it can still legitimately shape approval_mode/export elsewhere in a future
    # version — but we surface it so pack authors notice.
    unused = arg_names - placeholders
    if unused:
        import warnings

        warnings.warn(
            f"command '{raw['id']}': argument(s) {sorted(unused)} declared but never used "
            f"in instruction_template.",
            stacklevel=2,
        )

    return CommandSpec(
        id=raw["id"],
        title=raw["title"],
        description=raw["description"],
        approval_mode=raw["approval_mode"],
        instruction_template=raw["instruction_template"],
        arguments=arguments,
        export=export,
        templates=templates,
        superdocs_tool=raw.get("superdocs_tool", "chat_async"),
    )


_APPROVAL_MODE_GUIDANCE = {
    "ask_every_time": (
        "- Tool: call `chat_async` (not `chat`) with `approval_mode=\"ask_every_time\"` — HITL review "
        "requires the async workflow.\n"
        "- Poll with `get_job` until status is `awaiting_approval`, then show the user every entry in "
        "`metadata.pending_changes` (old vs. new content, per change) and get an explicit yes/no on each "
        "one BEFORE calling `approve_change`. Do not auto-approve on this command — that defeats the "
        "point of a redline/edit workflow.\n"
        "- If the user rejects a change, pass `approved=false` with their `feedback` on that `change_id` "
        "so the AI can revise just that item; keep polling through further `awaiting_approval` rounds "
        "until `status` is `completed`."
    ),
    "approve_all": (
        "- Tool: call `chat` (synchronous) or `chat_async` with `approval_mode=\"approve_all\"` — this "
        "command produces new/summary content rather than editing existing binding text, so it applies "
        "immediately without a per-change review gate.\n"
        "- Still show the user the AI's response before exporting, so they can ask for a follow-up edit "
        "if something looks off."
    ),
}


def _template_guidance(spec: TemplateSpec) -> str:
    if not spec.use_saved:
        return ""
    hint = f" {spec.hint}" if spec.hint else ""
    return (
        "- Templates: call `list_user_templates` FIRST and draft from the user's own saved template."
        f"{hint} If no saved template matches, say so and offer to have them upload one with "
        "`upload_template_base64` — do NOT invent house-standard language to fill the gap. "
        "Drafting a clause the organisation never approved, in a document that looks like theirs, "
        "is worse than an honest 'you have no template for this yet'.\n"
    )


def render_full_prompt(command: CommandSpec, provided: dict[str, str]) -> str:
    """The complete text handed to the assistant when this slash command is invoked:
    the rendered task instruction plus explicit, unambiguous SuperDocs MCP tool
    call settings — approval mode, template sourcing, and export settings included,
    so an agent reading this prompt in ANY client makes the same tool calls every time."""
    task = command.render(provided)
    guidance = _APPROVAL_MODE_GUIDANCE[command.approval_mode]
    export_options = f", options={command.export.options!r}" if command.export.options else ""
    return (
        f"{task}\n\n"
        "--- SuperDocs call settings for this workflow (do not deviate) ---\n"
        f"{_template_guidance(command.templates)}"
        f"{guidance}\n"
        f"- When the work is approved and complete, call `export_document` with "
        f"format=\"{command.export.format}\"{export_options}.\n"
        "- If the SuperDocs MCP server isn't connected in this client, tell the user to connect it first "
        "(docs.superdocs.app/mcp/mcp-setup) before attempting any of the above."
    )


def load_pack(path: str | Path) -> PackSpec:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for required_field in ("pack_id", "display_name", "description", "vertical", "commands"):
        if required_field not in data:
            raise PackSpecError(f"{path}: pack missing required top-level field '{required_field}'")

    if not data["commands"]:
        raise PackSpecError(f"{path}: pack has no commands")

    valid_id = re.compile(r"^[a-z][a-z0-9_]*$")
    if not valid_id.match(data["pack_id"]):
        raise PackSpecError(
            f"{path}: pack_id '{data['pack_id']}' must be lowercase snake_case "
            f"(it becomes part of the MCP server/tool namespace)."
        )

    commands = [_parse_command(c) for c in data["commands"]]

    seen_ids: set[str] = set()
    for c in commands:
        if not valid_id.match(c.id):
            raise PackSpecError(f"{path}: command id '{c.id}' must be lowercase snake_case.")
        if c.id in seen_ids:
            raise PackSpecError(f"{path}: duplicate command id '{c.id}'.")
        seen_ids.add(c.id)

    return PackSpec(
        pack_id=data["pack_id"],
        display_name=data["display_name"],
        description=data["description"],
        vertical=data["vertical"],
        commands=commands,
    )
