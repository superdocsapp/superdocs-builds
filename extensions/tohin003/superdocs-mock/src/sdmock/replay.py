"""The replay engine: turn a request into the response that was recorded for it.

Shared by both transports (D7). The REST app and the MCP server call the same
``Library.resolve`` and therefore cannot drift apart -- which is what makes the parity
test in the contract suite meaningful rather than circular.

Three ideas carry the whole design:

**Templated matching.** Interactions are keyed by (method, spec path template), not by the
concrete path that happened to be recorded. A cassette captured against session
`sdmock-review-001` replays for a client using `my-app-session-42`.

**Ordered cursors.** Several interactions can share one key -- a job poll returns
`in_progress`, then `awaiting_approval`, then `completed`. The cursor walks them in
recorded order and holds on the last one, so a client's polling loop terminates instead
of spinning. That is the whole job state machine, and it is data rather than code.

**Isolated state.** Cursors live under (scenario, run). Two scenarios never share state,
and a client that wants two independent runs of the *same* scenario sends `X-Mock-Run`.
Concurrency does not corrupt a replay; it just gets its own cursor.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from .cassette import Cassette, Interaction, load_all
from .spec import Spec, load as load_spec

from .paths import cassettes_dir

SCENARIO_HEADER = "x-mock-scenario"
RUN_HEADER = "x-mock-run"
LATENCY_HEADER = "x-mock-latency"


class ScenarioNotFound(LookupError):
    """Raised for an unknown scenario id. Carries the catalogue so the error can help."""

    def __init__(self, requested: str, available: list[str]) -> None:
        self.requested = requested
        self.available = available
        super().__init__(requested)


class InteractionNotFound(LookupError):
    """Raised when a scenario has no recording for a request it received."""

    def __init__(self, method: str, template: str, scenario: str,
                 available: list[str]) -> None:
        self.method = method
        self.template = template
        self.scenario = scenario
        self.available = available
        super().__init__(f"{method} {template}")


@dataclass(frozen=True)
class Resolution:
    """One matched interaction, plus the context needed to answer honestly."""

    interaction: Interaction
    cassette: Cassette
    template: str
    exhausted: bool  # True when the cursor is repeating its final recording


class Library:
    """Every cassette on disk, indexed for replay."""

    def __init__(self, directory: Path | None = None, spec: Spec | None = None) -> None:
        self.directory = directory or cassettes_dir()
        self.spec = spec or load_spec()
        self.cassettes = load_all(self.directory)
        self._index: dict[str, dict[tuple[str, str], list[Interaction]]] = {}
        self._cursors: dict[tuple[str, str, str, str], int] = {}
        self._lock = threading.Lock()
        self._build_index()

    # ---------------------------------------------------------------- indexing

    def _build_index(self) -> None:
        for name, cassette in self.cassettes.items():
            table: dict[tuple[str, str], list[Interaction]] = {}
            for interaction in cassette.interactions:
                template = self.spec.match(interaction.request.path)
                key = (interaction.request.method.upper(), template
                       or interaction.request.path)
                table.setdefault(key, []).append(interaction)
            self._index[name] = table

    @property
    def scenarios(self) -> list[str]:
        return sorted(self.cassettes)

    def default_scenario(self) -> str:
        """The scenario served when a caller names none.

        The four-call happy path is the right default: a client pointed at the mock with
        no configuration at all should get a working document flow, not an error.
        """
        for preferred in ("proposed-change-batch", "styled-document"):
            if preferred in self.cassettes:
                return preferred
        return self.scenarios[0]

    def catalogue(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for name, cassette in sorted(self.cassettes.items()):
            rows.append({
                "scenario": name,
                "description": cassette.description,
                "synthesised": cassette.synthesised,
                "synthesis_note": cassette.synthesis_note,
                "recorded_at": cassette.recorded_at,
                "covers": sorted(cassette.covers),
                "endpoints": sorted({f"{m} {t}" for (m, t) in self._index[name]}),
                "interactions": len(cassette.interactions),
            })
        return rows

    # ---------------------------------------------------------------- resolution

    @staticmethod
    def _affinity(recorded: Interaction, body: dict | None) -> int:
        """How well an incoming request body matches a recorded one.

        When a scenario holds several recordings for one route, cursor order alone is a
        poor discriminator. `POST /v1/documents/export` was recorded twice -- once with
        `format: "docx"` returning a DOCX, once with `format: "pages"` returning the
        documented 422 -- and a caller asking for an invalid format should get the 422
        whichever order the tests happen to run in.

        So candidates are scored on how many top-level scalar fields they share with the
        incoming body, and the best match wins; cursor order breaks ties and remains the
        rule when nothing distinguishes them. Scalars only, deliberately: comparing
        nested document HTML would be slow and would match on noise.
        """
        if not isinstance(body, dict):
            return 0
        recorded_body = recorded.request.json_body
        if not isinstance(recorded_body, dict):
            return 0
        score = 0
        for key, value in recorded_body.items():
            if not isinstance(value, (str, int, float, bool)) or isinstance(value, bool):
                if not isinstance(value, bool):
                    continue
            if key not in body:
                continue
            score += 2 if body[key] == value else -1
        return score

    def resolve(
        self,
        method: str,
        path: str,
        *,
        scenario: str | None = None,
        run: str = "default",
        advance: bool = True,
        body: dict | None = None,
    ) -> Resolution:
        """Find the recorded response for this request, advancing the cursor."""
        name = scenario or self.default_scenario()
        cassette = self.cassettes.get(name)
        if cassette is None:
            raise ScenarioNotFound(name, self.scenarios)

        template = self.spec.match(path) or path
        key = (method.upper(), template)
        recordings = self._index[name].get(key)
        if not recordings:
            raise InteractionNotFound(
                method.upper(), template, name,
                sorted({f"{m} {t}" for (m, t) in self._index[name]}),
            )

        cursor_key = (name, run, method.upper(), template)
        with self._lock:
            position = self._cursors.get(cursor_key, 0)
            exhausted = position >= len(recordings) - 1
            index = min(position, len(recordings) - 1)

            # A body that clearly names one recording overrides cursor order, so an
            # invalid request gets its recorded rejection whatever the test order.
            if body is not None and len(recordings) > 1:
                scores = [self._affinity(r, body) for r in recordings]
                best = max(scores)
                if best > 0 and scores[index] < best:
                    index = scores.index(best)
                    exhausted = False  # a targeted match does not consume the sequence
                elif advance and not exhausted:
                    self._cursors[cursor_key] = position + 1
            elif advance and not exhausted:
                self._cursors[cursor_key] = position + 1

        return Resolution(
            interaction=recordings[index],
            cassette=cassette,
            template=template,
            exhausted=exhausted,
        )

    def event_history(
        self, path: str, *, scenario: str | None = None
    ) -> tuple[list, Cassette]:
        """Every SSE frame recorded for a route, merged into one ordered history.

        A stream is not a sequence of separate responses -- it is one event history that
        a client may attach to more than once. A cassette can therefore hold several
        recordings of the same stream (an initial attach, then a resume after approval),
        and the right replay is their union, filtered by `last_sequence`, not "hand out
        the next recording".

        Getting this wrong is subtle and was: cursor semantics made a resume from
        sequence 2 return *more* frames than the full stream, because it served the
        second recording rather than filtering the first.

        Duplicates are removed on (event, data) rather than on sequence, because the live
        service emits two different events sharing sequence 11 (finding F-006) and the
        mock's job is to reproduce that faithfully, not to tidy it away.
        """
        name = scenario or self.default_scenario()
        cassette = self.cassettes.get(name)
        if cassette is None:
            raise ScenarioNotFound(name, self.scenarios)

        template = self.spec.match(path) or path
        recordings = self._index[name].get(("GET", template))
        if not recordings:
            raise InteractionNotFound(
                "GET", template, name,
                sorted({f"{m} {t}" for (m, t) in self._index[name]}),
            )

        frames: list = []
        seen: set[tuple[str, str]] = set()
        for interaction in recordings:
            for frame in interaction.response.sse or []:
                signature = (frame.event, frame.data)
                if signature in seen:
                    continue
                seen.add(signature)
                frames.append(frame)
        frames.sort(key=lambda f: (f.sequence if f.sequence is not None else 0))
        return frames, cassette

    def reset(self, scenario: str | None = None, run: str | None = None) -> int:
        """Rewind cursors so a test can replay a scenario from the top.

        Returns how many cursors were cleared. Exposed over HTTP as well, because a test
        suite that cannot rewind its own fixtures ends up depending on test order.
        """
        with self._lock:
            doomed = [
                key for key in self._cursors
                if (scenario is None or key[0] == scenario)
                and (run is None or key[1] == run)
            ]
            for key in doomed:
                del self._cursors[key]
        return len(doomed)
