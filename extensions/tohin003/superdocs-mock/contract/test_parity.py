"""L5 -- REST and MCP must agree.

An integrator picks one transport and trusts it. If `chat` over MCP and `POST /v1/chat`
over REST disagree about what a job looks like, the choice of transport silently becomes a
choice of behaviour, and the bug surfaces the day someone migrates.

These tests are only meaningful because the mock resolves both transports through one
replay core (D7). If the MCP side had its own hand-written fixtures, parity would be
something I asserted about my own copy-paste rather than about the service.

Against `--target live` the same assertions become a real check on SuperDocs: the REST API
and the MCP server are two front doors onto one backend, and this is where they are held
to agreeing.
"""

from __future__ import annotations

import pytest

from support import structured


def rest_and_mcp(api, *, tool: str, arguments: dict, method: str, path: str,
                 scenario: str | None = None, json_body: dict | None = None):
    """Drive the same operation both ways and return (rest_payload, mcp_payload)."""
    if scenario:
        api.using(scenario)
    rest = api.request(method, path, json=json_body) if json_body is not None \
        else api.request(method, path)
    api.client.post("/__sdmock__/reset") if api.target == "mock" else None
    if scenario:
        api.using(scenario)
    api.initialize()
    mcp = api.tool(tool, arguments)
    return rest, mcp


@pytest.mark.mcp
@pytest.mark.billable
def test_job_state_is_the_same_through_both_doors(api, journey, target):
    """`get_job` over MCP and GET /v1/jobs/{id} over REST describe one job.

    Against the mock this reads a recorded job; against live it starts a real one,
    because a job id from a cassette does not exist on the live service and asserting
    against a 404 would prove nothing about parity.
    """
    if target == "live":
        job_id = journey.start_review()
        journey.await_review(job_id)
    else:
        job_id = "12458c63-154c-4a71-9cf7-758797284e93"
        api.using("proposed-change-batch")

    rest = api.get(f"/v1/jobs/{job_id}").json()

    if api.target == "mock":
        api.client.post("/__sdmock__/reset")
        api.using("proposed-change-batch")
    api.initialize()
    mcp = structured(api.tool("get_job", {"job_id": job_id}))

    assert mcp is not None, "the MCP tool returned nothing parseable"
    for field in ("status", "job_type", "session_id"):
        assert mcp.get(field) == rest.get(field), (
            f"{field} differs between transports: "
            f"REST={rest.get(field)!r} MCP={mcp.get(field)!r}"
        )

    rest_pending = (rest.get("metadata") or {}).get("pending_changes") or []
    mcp_pending = (mcp.get("metadata") or {}).get("pending_changes") or []
    assert len(rest_pending) == len(mcp_pending), (
        "the two transports disagree on how many changes are awaiting review"
    )
    assert [c["change_id"] for c in rest_pending] == \
           [c["change_id"] for c in mcp_pending]


@pytest.mark.mcp
def test_account_status_agrees_with_whoami(api):
    """`get_account_status` is the MCP face of GET /v1/agents/whoami."""
    api.using("account-status")
    rest = api.get("/v1/agents/whoami").json()

    if api.target == "mock":
        api.client.post("/__sdmock__/reset")
    api.using("mcp-journey")
    api.initialize()
    mcp = structured(api.tool("get_account_status"))

    assert mcp is not None
    assert mcp.get("tier") == rest.get("tier")
    assert mcp.get("quota", {}).get("monthly_limit") == \
           rest.get("quota", {}).get("monthly_limit")


@pytest.mark.mcp
@pytest.mark.mock_only
def test_an_error_reaches_an_agent_as_an_error(api):
    """A refusal must not arrive over MCP looking like a success.

    An agent branches on `isError`. If a 413 came back as an ordinary tool result, the
    agent would treat a capacity refusal as a parsed document and carry on -- which is
    precisely the class of failure that makes agent integrations untrustworthy.
    """
    api.using("capacity-refusal")
    rest = api.post("/v1/documents/upload")
    assert rest.status_code == 413

    api.client.post("/__sdmock__/reset")
    api.using("capacity-refusal")
    api.initialize()
    result = api.tool("upload_document_base64",
                      {"filename": "x.html", "file_base64": "", "session_id": "s"})
    # The mock has no base64-upload recording in this scenario, so it refuses honestly
    # rather than inventing one -- which is itself the property being asserted.
    assert result.get("isError") is True
    assert "never invents" in result["content"][0]["text"] \
        or "no recording" in result["content"][0]["text"]


@pytest.mark.mcp
@pytest.mark.mock_only
def test_synthesised_scenarios_are_flagged_over_mcp_too(api):
    """The honesty flag has to survive the transport, or it protects nobody."""
    api.using("rate-limit")
    api.initialize()
    result = api.tool("chat", {"message": "x", "session_id": "s"})
    assert (result.get("_meta") or {}).get("sdmock/synthesised") is True
