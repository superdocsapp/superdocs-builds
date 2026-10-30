"""The cassette format: one recorded scenario, on disk, replayable forever.

A cassette is the unit this whole project trades in. It holds the interactions of one
scenario in the order they happened, so a replay can reproduce not just single responses
but a lifecycle -- the same GET /v1/jobs/{id} returning in_progress, then
awaiting_approval, then completed, exactly as the live service did.

Design notes worth keeping in mind:

* Matching is by (method, path) within a scenario, with an ordered cursor per key. The
  first request to a key gets the first recording, the second gets the second, and once
  the recordings run out the last one repeats. That is what makes polling loops work
  without hand-written state machines.

* Paths are stored concretely, not templated. The mock hands the client the recorded
  job id, so the client's next URL is byte-identical to the recorded one. Templating
  would be more general and would buy nothing.

* Serialization is canonical -- sorted keys, fixed separators, trailing newline. Two
  recordings of the same traffic produce the same file, so a diff means a real change.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA = "sdmock/cassette@1"


@dataclass
class SSEFrame:
    """One server-sent event, with the offset at which it arrived."""

    event: str
    data: str
    offset_ms: int = 0
    sequence: int | None = None


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any | None = None
    text_body: str | None = None
    multipart: list[dict[str, Any]] | None = None


@dataclass
class RecordedResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any | None = None
    text_body: str | None = None
    base64_body: str | None = None
    sse: list[SSEFrame] | None = None

    @property
    def body_bytes(self) -> bytes:
        if self.base64_body is not None:
            return base64.b64decode(self.base64_body)
        if self.json_body is not None:
            return dumps(self.json_body).encode("utf-8")
        return (self.text_body or "").encode("utf-8")


@dataclass
class Interaction:
    id: str
    transport: str  # "rest" | "mcp"
    request: RecordedRequest
    response: RecordedResponse
    elapsed_ms: int = 0
    billable: bool = False
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.request.method.upper(), self.request.path)


@dataclass
class Cassette:
    scenario: str
    description: str
    interactions: list[Interaction] = field(default_factory=list)
    recorded_at: str = ""
    recorded_against: dict[str, str] = field(default_factory=dict)
    spec_pin: str = ""
    covers: list[str] = field(default_factory=list)  # B-IDs this scenario exercises
    schema: str = SCHEMA

    # A cassette is either recorded off the live service or built from a documented
    # shape. The two are never allowed to look alike: `synthesised` is surfaced in the
    # scenario catalogue, in the mock's own responses, and in the README. A fixture that
    # quietly passes itself off as a recording is the one dishonesty a mock must not
    # commit -- it is the whole reason anyone trusts the rest of the fixtures.
    synthesised: bool = False
    synthesis_note: str = ""

    # ---------------------------------------------------------------- persistence

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "scenario": self.scenario,
            "description": self.description,
            "recorded_at": self.recorded_at,
            "recorded_against": self.recorded_against,
            "spec_pin": self.spec_pin,
            "covers": sorted(self.covers),
            "synthesised": self.synthesised,
            "synthesis_note": self.synthesis_note,
            "interactions": [_prune(asdict(i)) for i in self.interactions],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Cassette":
        if raw.get("schema") != SCHEMA:
            raise ValueError(f"unsupported cassette schema: {raw.get('schema')!r}")
        interactions = []
        for item in raw.get("interactions", []):
            response = dict(item["response"])
            frames = response.pop("sse", None)
            interactions.append(
                Interaction(
                    id=item["id"],
                    transport=item.get("transport", "rest"),
                    request=RecordedRequest(**item["request"]),
                    response=RecordedResponse(
                        **response,
                        sse=[SSEFrame(**f) for f in frames] if frames else None,
                    ),
                    elapsed_ms=item.get("elapsed_ms", 0),
                    billable=item.get("billable", False),
                    note=item.get("note", ""),
                )
            )
        return cls(
            scenario=raw["scenario"],
            description=raw.get("description", ""),
            interactions=interactions,
            recorded_at=raw.get("recorded_at", ""),
            recorded_against=raw.get("recorded_against", {}),
            spec_pin=raw.get("spec_pin", ""),
            covers=raw.get("covers", []),
            synthesised=raw.get("synthesised", False),
            synthesis_note=raw.get("synthesis_note", ""),
        )

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.scenario}.json"
        path.write_text(dumps(self.to_dict()) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Cassette":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    # ---------------------------------------------------------------- replay

    def index(self) -> dict[tuple[str, str], list[Interaction]]:
        out: dict[tuple[str, str], list[Interaction]] = {}
        for interaction in self.interactions:
            out.setdefault(interaction.key, []).append(interaction)
        return out

    @property
    def billable_count(self) -> int:
        return sum(1 for i in self.interactions if i.billable)


def load_all(directory: Path) -> dict[str, Cassette]:
    """Load every cassette in a directory, keyed by scenario id."""
    cassettes: dict[str, Cassette] = {}
    for path in sorted(directory.glob("*.json")):
        cassette = Cassette.load(path)
        if cassette.scenario in cassettes:
            raise ValueError(f"duplicate scenario id {cassette.scenario!r} in {path}")
        cassettes[cassette.scenario] = cassette
    return cassettes


def iter_frames(response: RecordedResponse) -> Iterator[SSEFrame]:
    yield from (response.sse or [])


def dumps(value: Any) -> str:
    """Canonical JSON. Determinism starts here."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


# Fields whose contents are recorded payload, never this format's own bookkeeping.
# Pruning must not reach inside them: an empty list in a response body is *data*, and
# deleting it changes what the mock replays.
_PAYLOAD_FIELDS = frozenset({"json_body", "text_body", "base64_body", "multipart",
                             "sse", "headers", "query"})


def _prune(value: Any, *, inside_payload: bool = False) -> Any:
    """Drop this format's own unset fields so cassettes stay readable in a diff.

    Only the wrapper is pruned -- the interaction, request and response objects -- and
    only of `None`. Recorded payloads are left exactly as they arrived.

    An earlier version pruned recursively and dropped every empty list and object it
    found, including ones inside response bodies. `GET /v1/users/me/promotions` returns
    `{"active": [...], "history": []}`, the empty `history` was deleted on the way to
    disk, and the schema check then reported a required property missing -- a finding
    against SuperDocs that was entirely this function's doing. Fixtures are evidence;
    tidying evidence is how you end up reporting your own bugs as someone else's.
    """
    if inside_payload:
        return value
    if isinstance(value, dict):
        return {
            key: _prune(val, inside_payload=key in _PAYLOAD_FIELDS)
            for key, val in value.items()
            if val is not None
        }
    if isinstance(value, list):
        return [_prune(item) for item in value]
    return value
