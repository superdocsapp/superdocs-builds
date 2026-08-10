"""L1 -- every response validated against the pinned OpenAPI schema for its operation.

This is the layer that catches shape drift for free, across all 81 routes, without anyone
having to think of the assertion first. It found F-004 on the first recorded call.

**How known drift is handled, and why it matters.**

A divergence that has been found, verified and reported is encoded here as a *strict*
xfail naming its finding. That gives the suite a useful meaning in both directions:

* green  -- the world is exactly as `docs/findings.md` describes it
* red    -- something moved: either a new divergence appeared, or a known one was fixed
            (a strict xfail that starts passing is a failure, and it should be -- it
            means the finding is stale and the mock is now reproducing a bug that no
            longer exists)

The alternative -- asserting strictly and living with a permanently red suite -- trains
people to ignore it, which is worse than having no suite. The alternative in the other
direction, quietly excluding the route, hides the very thing this project exists to find.
"""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from sdmock.spec import load as load_spec

# Schema-level divergences confirmed against the live service, keyed by
# (method, template, status). Currently empty: every response this suite has observed
# validates against the schema its route publishes. The registry stays because the day
# one does not is the day this matters, and an empty registry is itself a claim worth
# making -- it says the sweep below ran and found nothing, not that nobody looked.
#
# It was briefly populated with an upload-route entry that turned out to be my error
# rather than SuperDocs': the route publishes an empty schema and never claimed
# ProcessDocumentResponse at all. See the retraction in docs/findings.md, F-004.
KNOWN_DRIFT: dict[tuple[str, str, int], str] = {}


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def validate(spec, method: str, path: str, status: int, payload) -> list[str]:
    """Return schema violations for a response, or an empty list."""
    template = spec.match(path)
    assert template, f"{path} is not a route in the pinned spec"
    schema = spec.response_schema(method, template, status)
    if schema is None:
        return []
    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(payload)
    ]


def check(spec, method: str, path: str, response) -> None:
    """Validate, honouring the known-drift registry."""
    template = spec.match(path)
    key = (method.upper(), template, response.status_code)
    problems = validate(spec, method, path, response.status_code, response.json())

    if key in KNOWN_DRIFT:
        if not problems:
            pytest.fail(
                f"{method} {template} now conforms to the spec, but "
                f"{KNOWN_DRIFT[key].split(':')[0]} says it should not. The divergence "
                "was fixed -- update docs/findings.md, drop it from KNOWN_DRIFT, and "
                "re-record the cassette."
            )
        pytest.xfail(KNOWN_DRIFT[key])

    assert not problems, (
        f"{method} {template} -> {response.status_code} violates its published schema:\n  "
        + "\n  ".join(problems)
    )


# ------------------------------------------------------------------ the routes


@pytest.mark.rest
def test_upload_response_matches_its_schema(spec, journey):
    """The multipart upload route.

    Vacuous as a schema check -- the route publishes `{}`, which accepts anything -- and
    that vacuity is exactly F-004. The assertion that carries weight is the one below,
    which pins the gap so it cannot close silently.
    """
    response = journey.upload()
    assert response.status_code == 200, response.text
    check(spec, "POST", "/v1/documents/upload", response)


@pytest.mark.rest
def test_upload_routes_still_publish_an_empty_schema(spec):
    """F-004, stated as a fact about the spec rather than about a response.

    If SuperDocs gives these routes a real schema, this fails and the finding gets
    closed. That is the outcome to want.
    """
    for template in ("/v1/documents/upload", "/v1/documents/upload-base64"):
        schema = spec.operation("post", template)["responses"]["200"] \
            .get("content", {}).get("application/json", {}).get("schema")
        assert schema == {}, (
            f"{template} now publishes a response schema -- F-004 is fixed, update "
            "docs/findings.md and delete this test"
        )


@pytest.mark.rest
def test_the_route_that_declares_process_document_response_conforms_to_it(spec, journey,
                                                                         api, target):
    """The large-file path, end to end, checked against the schema it actually claims.

    Pre-signed upload, PUT to storage, then process -- the flow the docs prescribe for
    documents too big to push through a request body, and the one the round asks for
    ("large real files handled through the upload path rather than in memory").

    This is also the check that retracted F-004: this route does reference
    ProcessDocumentResponse, and it satisfies it exactly.
    """
    if target == "mock":
        api.using("large-file-upload")
        response = api.post("/v1/uploads/x/process", json={})
    else:
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "corpus" \
            / "master-services-agreement.docx"
        payload = source.read_bytes()
        docx = ("application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document")
        granted = api.post("/v1/uploads", json={
            "filename": source.name, "content_type": docx,
            "size_bytes": len(payload), "purpose": "document"}).json()
        api.client.put(granted["upload_url"], content=payload,
                       headers={"Content-Type": docx})
        response = api.post(
            f"/v1/uploads/{granted['upload_id']}/process",
            json={"upload_id": granted["upload_id"], "filename": source.name,
                  "session_id": journey.session_id, "parse_mode": "document"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] and body["parse_mode"], (
        "both are declared required by ProcessDocumentResponse"
    )
    check(spec, "POST", "/v1/uploads/{upload_id}/process", response)


@pytest.mark.rest
@pytest.mark.billable
def test_async_chat_response_matches_its_schema(spec, journey, api):
    """AsyncChatResponse: job_id, session_id, status are all required."""
    job_id = journey.start_review()
    assert job_id
    # Re-fetch through the documented shape rather than trusting the local variable.
    response = api.get(f"/v1/jobs/{job_id}")
    check(spec, "GET", "/v1/jobs/{job_id}", response)


@pytest.mark.rest
@pytest.mark.billable
def test_job_response_matches_its_schema(spec, journey, api):
    """JobResponse, at the point where it is carrying the most structure."""
    job_id = journey.start_review()
    body = journey.await_review(job_id)
    assert body.get("status") in {"awaiting_approval", "completed"}
    response = api.get(f"/v1/jobs/{job_id}")
    check(spec, "GET", "/v1/jobs/{job_id}", response)


@pytest.mark.rest
def test_export_declared_json_is_actually_binary(spec, journey):
    """F-002, asserted rather than described.

    The spec declares this 200 as application/json. It is a DOCX. Rather than xfail a
    schema check that cannot run at all on ZIP bytes, this asserts the *truth* -- and
    fails loudly if the response ever becomes JSON, because that would mean either the
    service changed or the mock stopped being faithful.
    """
    response = journey.export()
    assert response.status_code == 200, response.text

    declared = spec.operation("post", "/v1/documents/export")["responses"]["200"]
    assert "application/json" in declared["content"], (
        "the spec no longer declares export as JSON -- F-002 may be fixed; re-check it"
    )
    assert response.content[:4] == b"PK\x03\x04", (
        "export stopped returning a ZIP container"
    )
    assert "wordprocessingml" in response.headers.get("content-type", "")
    assert "attachment" in response.headers.get("content-disposition", "")


@pytest.mark.rest
def test_out_of_enum_export_format_is_a_422(spec, journey, api):
    """B-076. Costs nothing on either target, so it runs against live for free."""
    response = journey.export(fmt="pages")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list), "422 should use the list-of-errors shape"
    assert detail[0]["loc"][-1] == "format"


@pytest.mark.rest
def test_every_recorded_response_conforms(spec, target):
    """Sweep every committed cassette through the schema check in one pass.

    Catches drift on routes no individual test thought to cover -- which is the whole
    argument for validating against a published spec rather than against hand-written
    expectations.
    """
    if target != "mock":
        pytest.skip("cassette sweep is about the recorded fixtures")

    from pathlib import Path

    from sdmock.cassette import load_all

    root = Path(__file__).resolve().parent.parent
    failures: list[str] = []
    drifted: list[str] = []

    for name, cassette in load_all(root / "cassettes").items():
        if cassette.synthesised:
            continue  # built from the spec by construction; nothing independent to learn
        for interaction in cassette.interactions:
            if interaction.transport != "rest":
                continue
            body = interaction.response.json_body
            if body is None:
                continue
            method = interaction.request.method
            template = spec.match(interaction.request.path)
            if template is None:
                continue
            key = (method.upper(), template, interaction.response.status)
            problems = validate(spec, method, interaction.request.path,
                                interaction.response.status, body)
            if not problems:
                continue
            line = f"{name}/{interaction.id}: {method} {template} -> " \
                   f"{interaction.response.status}: {problems[0]}"
            (drifted if key in KNOWN_DRIFT else failures).append(line)

    assert not failures, (
        "recorded responses violate the published spec, and these are not known "
        "divergences:\n  " + "\n  ".join(failures)
    )
    # Every entry in KNOWN_DRIFT must still be observable. A registry that outlives the
    # divergence it describes is how a suite starts lying about the world.
    unobserved = set(KNOWN_DRIFT) - {
        (m, t, s_) for m, t, s_ in [
            (line.split(": ")[1].split(" ")[0], line.split(" ")[2], 0) for line in drifted
        ]
    } if drifted else set(KNOWN_DRIFT)
    assert not (KNOWN_DRIFT and unobserved and not drifted), (
        "a known divergence was not observed in any cassette -- it may be fixed; "
        f"re-check {sorted(unobserved)} against docs/findings.md"
    )
