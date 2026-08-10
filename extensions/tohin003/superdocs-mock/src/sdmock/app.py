"""The mock server: SuperDocs' REST API and MCP server, on one port, from cassettes.

Layout mirrors the real service deliberately -- `/v1/*` and `/mcp/` on the same origin
behind the same bearer token -- so an integrator redirects one base URL and both halves of
their stack follow. Anything else would make the mock a different shape from the thing it
stands in for.

Routing is a single catch-all rather than a hand-written route table. The route table is
the pinned `openapi.json`: a path the spec does not describe gets an honest 404 that says
so, and a path it does describe but this scenario never recorded gets a 501 that lists
what the scenario *does* cover. Neither invents a response, because a mock that guesses is
worse than no mock at all.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from . import __version__, mutants
from .cassette import Interaction, dumps
from .mcp.server import MCPServer
from .replay import (
    LATENCY_HEADER,
    RUN_HEADER,
    SCENARIO_HEADER,
    InteractionNotFound,
    Library,
    ScenarioNotFound,
)

REQUIRE_AUTH = os.environ.get("SDMOCK_REQUIRE_AUTH", "true").lower() != "false"
DEFAULT_SCENARIO_ENV = "SDMOCK_DEFAULT_SCENARIO"


def _canonical(payload: Any) -> Response:
    """JSON with sorted keys, so two runs are byte-identical (determinism, D6)."""
    return Response(
        dumps(payload) + "\n",
        media_type="application/json",
        headers={"cache-control": "no-store"},
    )


def problem(status: int, cause: str, fix: str, **extra: Any) -> Response:
    """An error that names the cause *and* the fix.

    Round criterion, and simple self-interest: every one of these is a message someone
    will read at 2am while their CI is red.
    """
    body: dict[str, Any] = {"detail": cause, "sdmock": {"cause": cause, "fix": fix}}
    body["sdmock"].update(extra)
    response = _canonical(body)
    response.status_code = status
    return response


class MockApp:
    def __init__(self, library: Library | None = None) -> None:
        self.library = library or Library()
        self.mcp = MCPServer(self.library)
        self.started = time.time()

    # ---------------------------------------------------------------- helpers

    def scenario_for(self, request: Request) -> str:
        return (
            request.headers.get(SCENARIO_HEADER)
            or request.query_params.get("scenario")
            or os.environ.get(DEFAULT_SCENARIO_ENV)
            or self.library.default_scenario()
        )

    def run_for(self, request: Request) -> str:
        return request.headers.get(RUN_HEADER, "default")

    def check_auth(self, request: Request) -> Response | None:
        """Reproduce the documented 401s so a client can test its auth path (B-002/3).

        Any bearer value is accepted -- this is a mock, and demanding a real key would
        defeat the point. What it will not accept is a *missing* or malformed header,
        because that is a bug worth catching in CI rather than in production.
        """
        if not REQUIRE_AUTH:
            return None
        header = request.headers.get("authorization")
        if header is None:
            return problem(
                401,
                "Invalid authorization header format. Expected 'Bearer <api_key>'",
                "Send Authorization: Bearer sk_test_anything. The mock accepts any "
                "value; set SDMOCK_REQUIRE_AUTH=false to drop the check entirely.",
            )
        if not header.lower().startswith("bearer ") or not header[7:].strip():
            return problem(
                401,
                "Invalid authorization header format. Expected 'Bearer <api_key>'",
                "Include the 'Bearer ' prefix and a non-empty value.",
            )
        return None

    def replay_headers(self, resolution: Any, scenario: str) -> dict[str, str]:
        headers = dict(resolution.interaction.response.headers)
        headers.pop("content-length", None)
        headers["x-mock-scenario"] = scenario
        headers["x-mock-interaction"] = resolution.interaction.id
        if resolution.cassette.synthesised:
            # Surfaced at runtime, not only in the catalogue: a caller should never have
            # to go and look up whether what they just received was ever observed.
            headers["x-mock-synthesised"] = "true"
        if resolution.exhausted:
            headers["x-mock-cursor"] = "final"
        return headers

    # ---------------------------------------------------------------- endpoints

    async def health(self, request: Request) -> Response:
        return _canonical({"status": "healthy"})

    async def catalogue(self, request: Request) -> Response:
        return _canonical({
            "sdmock": __version__,
            "spec_version": self.library.spec.version,
            "default_scenario": self.library.default_scenario(),
            "scenario_header": SCENARIO_HEADER,
            "run_header": RUN_HEADER,
            "scenarios": self.library.catalogue(),
        })

    async def reset(self, request: Request) -> Response:
        cleared = self.library.reset(
            scenario=request.query_params.get("scenario"),
            run=request.query_params.get("run"),
        )
        return _canonical({"reset": True, "cursors_cleared": cleared})

    async def stream(self, request: Request) -> Response:
        """Replay a recorded SSE stream, honouring last_sequence resume (B-056).

        Auth rides the query string here because EventSource cannot set headers (B-004),
        which is exactly why the real service does the same.
        """
        if REQUIRE_AUTH and not request.query_params.get("api_key"):
            return problem(
                401,
                "Invalid authorization header format. Expected 'Bearer <api_key>'",
                "EventSource cannot send headers, so this route takes ?api_key=... "
                "instead. Any value is accepted.",
            )

        scenario = self.scenario_for(request)
        try:
            frames, cassette = self.library.event_history(
                request.url.path, scenario=scenario
            )
        except ScenarioNotFound as exc:
            return self.unknown_scenario(exc)
        except InteractionNotFound as exc:
            return self.unrecorded(exc)

        total = len(frames)
        raw_last = request.query_params.get("last_sequence")
        last_sequence = int(raw_last) if raw_last and raw_last.isdigit() else 0

        # The mutant hook receives the *unfiltered* history and the requested cursor, so
        # a defect like "ignore last_sequence entirely" can be expressed at all. Filtering
        # first made that mutant a no-op, and the kill matrix caught it -- which is a fair
        # reminder that the mutants themselves need to be falsifiable too.
        mutant = mutants.active()
        if mutant is not None and mutant.sse is not None:
            frames = mutant.sse(frames, last_sequence)
        elif last_sequence:
            frames = [f for f in frames if (f.sequence or 0) > last_sequence]

        realistic = request.headers.get(LATENCY_HEADER, "").lower() == "realistic"

        async def body() -> AsyncIterator[bytes]:
            import asyncio

            previous = 0
            for frame in frames:
                if realistic:
                    gap = max(0, frame.offset_ms - previous) / 1000
                    previous = frame.offset_ms
                    if gap:
                        await asyncio.sleep(gap)
                yield f"event: {frame.event}\ndata: {frame.data}\n\n".encode("utf-8")

        headers = {
            "cache-control": "no-store",
            "x-mock-scenario": scenario,
            "x-mock-frames": str(len(frames)),
            "x-mock-frames-total": str(total),
        }
        if cassette.synthesised:
            headers["x-mock-synthesised"] = "true"
        return StreamingResponse(body(), media_type="text/event-stream", headers=headers)

    async def catch_all(self, request: Request) -> Response:
        """Every /v1 route, resolved through the spec and served from a cassette."""
        denied = self.check_auth(request)
        if denied is not None:
            return denied

        path = request.url.path
        template = self.library.spec.match(path)
        if template is None:
            return problem(
                404,
                f"No route {request.method} {path} exists in the SuperDocs API",
                "Check the path against the pinned specification "
                f"(OpenAPI {self.library.spec.version}). This mock serves only routes "
                "the published spec describes.",
            )
        if request.method.upper() not in self.library.spec.methods(template):
            return problem(
                405,
                f"{request.method} is not allowed on {template}",
                "The spec allows: "
                + ", ".join(sorted(self.library.spec.methods(template))),
            )

        body: dict[str, Any] | None = None
        if request.method.upper() in {"POST", "PUT", "PATCH"}:
            raw = await request.body()
            if raw:
                try:
                    parsed = json.loads(raw)
                    body = parsed if isinstance(parsed, dict) else None
                except ValueError:
                    body = None  # multipart or binary; matched on route alone

        scenario = self.scenario_for(request)
        try:
            resolution = self.library.resolve(
                request.method, path, scenario=scenario,
                run=self.run_for(request), body=body,
            )
        except ScenarioNotFound as exc:
            return self.unknown_scenario(exc)
        except InteractionNotFound as exc:
            return self.unrecorded(exc)

        return self.render(resolution, scenario, template, request.method)

    # ---------------------------------------------------------------- rendering

    def render(self, resolution: Any, scenario: str,
               template: str = "", method: str = "GET") -> Response:
        recorded = resolution.interaction.response
        headers = self.replay_headers(resolution, scenario)
        status = recorded.status
        json_body = recorded.json_body

        mutant = mutants.active()
        if mutant is not None and mutant.response is not None:
            status, headers, json_body = mutant.response(
                method, template or resolution.template, status, dict(headers), json_body
            )
            headers["x-mock-mutant"] = mutant.id

        if recorded.base64_body is not None and json_body is None:
            return Response(
                base64.b64decode(recorded.base64_body),
                status_code=status,
                headers=headers,
                media_type=headers.get("content-type", "application/octet-stream"),
            )
        if json_body is not None:
            return Response(
                dumps(json_body) + "\n",
                status_code=status,
                headers=headers,
                media_type="application/json",
            )
        return Response(
            recorded.text_body or "",
            status_code=status,
            headers=headers,
            media_type=headers.get("content-type", "text/plain"),
        )

    def unknown_scenario(self, exc: ScenarioNotFound) -> Response:
        return problem(
            400,
            f"Unknown scenario {exc.requested!r}",
            f"Set {SCENARIO_HEADER} to one of the scenarios listed in "
            "'available', or omit it to get the default. "
            "GET /__sdmock__/catalogue describes each one.",
            available=exc.available,
        )

    def unrecorded(self, exc: InteractionNotFound) -> Response:
        """A route the spec has but this scenario never recorded.

        Honestly absent beats present and broken: this returns 501 and says which
        scenario to switch to, rather than synthesising a plausible-looking body that a
        test would then encode as truth.
        """
        return problem(
            501,
            f"Scenario {exc.scenario!r} has no recording for "
            f"{exc.method} {exc.template}",
            "Switch scenarios with the "
            f"{SCENARIO_HEADER} header, or capture this call with "
            "`sdmock record`. This mock never invents a response it has not observed.",
            scenario=exc.scenario,
            recorded_in_this_scenario=exc.available,
        )

    # ---------------------------------------------------------------- MCP

    async def mcp_endpoint(self, request: Request) -> Response:
        denied = self.check_auth(request)
        if denied is not None:
            return denied
        try:
            payload = json.loads(await request.body() or b"{}")
        except ValueError:
            return _canonical({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32700, "message": "Parse error: body is not valid JSON"}})

        scenario = self.scenario_for(request)
        result = self.mcp.handle(payload, scenario=scenario, run=self.run_for(request))
        if result is None:  # a notification: acknowledged, nothing to return
            return Response(status_code=202)
        response = _canonical(result)
        response.headers["mcp-session-id"] = self.mcp.session_id
        response.headers["x-mock-scenario"] = scenario
        return response

    # ---------------------------------------------------------------- wiring

    def build(self) -> Starlette:
        routes = [
            Route("/health", self.health, methods=["GET"]),
            Route("/__sdmock__/catalogue", self.catalogue, methods=["GET"]),
            Route("/__sdmock__/reset", self.reset, methods=["POST", "GET"]),
            Route("/mcp", self.mcp_endpoint, methods=["POST", "GET"]),
            Route("/mcp/", self.mcp_endpoint, methods=["POST", "GET"]),
            Route("/v1/chat/{session_id}/stream", self.stream, methods=["GET"]),
            Route(
                "/{path:path}",
                self.catch_all,
                methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            ),
        ]
        return Starlette(routes=routes)


def create_app(library: Library | None = None) -> Starlette:
    return MockApp(library).build()
