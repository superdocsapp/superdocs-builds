#!/usr/bin/env python3
"""Build the cassettes that cannot honestly be recorded, from their documented shapes.

Two of the five scenarios the build calls for cannot be captured off the live service by
any responsible means:

* **rate-limit** -- an application 429 on quota exhaustion. Recording it means spending
  the account's entire remaining balance (10,500 operations at the time of writing) to
  produce one fixture. That is not a defensible use of someone's quota.
* **rate-limit-surge** -- the infrastructure 429 fires under platform-wide load. It
  cannot be induced by a single caller at all, and trying would mean deliberately
  loading a small team's production service.

The other cooldown that could produce a real 429 is the limit-increase endpoint, which
notifies the SuperDocs team on every call. Hammering a founder's inbox to record a
fixture is worse than synthesising one.

So these are built from the documented shape and **marked `synthesised: true`**. The mock
surfaces that flag on every response it serves from them, the scenario catalogue prints
it, and the contract suite skips them when run against the live target because there is
nothing there to compare against. An integrator is never misled about which fixtures are
recordings and which are reconstructions.

Sources: /errors/rate-limits and /errors/error-codes, pinned commit ac0d44c.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sdmock.cassette import (  # noqa: E402
    Cassette,
    Interaction,
    RecordedRequest,
    RecordedResponse,
)

CASSETTES = ROOT / "cassettes"
SPEC_PIN = "ac0d44c3d031fd0e338e7e78839162904ee69e79"
RECORDED_AT = "2026-08-10T00:00:00+00:00"  # fixed: synthesis is not an observation


def base(scenario: str, description: str, note: str, covers: list[str]) -> Cassette:
    return Cassette(
        scenario=scenario,
        description=description,
        covers=covers,
        recorded_at=RECORDED_AT,
        recorded_against={"base_url": "https://api.superdocs.app", "server": "n/a"},
        spec_pin=SPEC_PIN,
        synthesised=True,
        synthesis_note=note,
    )


def rate_limit() -> Cassette:
    """The application 429: JSON body, Retry-After, and the three X-Usage-* headers."""
    c = base(
        "rate-limit",
        "Quota exhaustion on a chat turn: the application 429, carrying Retry-After and "
        "the X-Usage-* headers that only appear on this response.",
        "Reconstructed from /errors/rate-limits, which prints this response verbatim "
        "including its headers. Recording it live would mean spending the account's "
        "entire remaining operation balance to produce one fixture.",
        ["B-064", "B-065", "B-067", "B-019"],
    )
    c.interactions.append(
        Interaction(
            id="i-001",
            transport="rest",
            request=RecordedRequest(
                method="POST",
                path="/v1/chat",
                headers={"content-type": "application/json"},
                json_body={
                    "message": "Tighten the record-keeping clause.",
                    "session_id": "sdmock-ratelimit-001",
                },
            ),
            response=RecordedResponse(
                status=429,
                headers={
                    "content-type": "application/json",
                    # Seconds until the monthly cycle resets, exactly as documented.
                    "retry-after": "1209600",
                    "x-usage-limit": "500",
                    "x-usage-used": "500",
                    "x-usage-remaining": "0",
                },
                json_body={
                    "detail": "Your monthly operation quota (500) is exhausted. "
                              "Upgrade to Pro for uninterrupted pay-as-you-go overage."
                },
            ),
            note="quota exhausted -- branch on the status and the headers, never the "
                 "detail wording (B-067)",
        )
    )
    return c


def rate_limit_surge() -> Cassette:
    """The infrastructure 429: plain text, no Retry-After, back off with jitter."""
    c = base(
        "rate-limit-surge",
        "A platform-level throttle: a plain-text 429 with no Retry-After, which a client "
        "must treat as transient rather than as a quota problem.",
        "Reconstructed from /errors/rate-limits. This response is emitted by the "
        "platform edge under load and cannot be induced by a single caller; attempting "
        "to would mean deliberately loading a live production service.",
        ["B-066", "B-067"],
    )
    c.interactions.append(
        Interaction(
            id="i-001",
            transport="rest",
            request=RecordedRequest(
                method="POST",
                path="/v1/chat",
                headers={"content-type": "application/json"},
                json_body={
                    "message": "Tighten the record-keeping clause.",
                    "session_id": "sdmock-ratelimit-002",
                },
            ),
            response=RecordedResponse(
                status=429,
                headers={"content-type": "text/plain"},
                text_body="Rate exceeded",
            ),
            note="non-JSON 429 with no Retry-After: transient, retry with exponential "
                 "backoff plus jitter (B-066)",
        )
    )
    return c


def paused_large_edit() -> Cassette:
    """The continue_prompt pause, and the 409 that guards it.

    Attempted live first, and the attempt is documented rather than hidden: a genuine
    400-section whole-document edit (job 9e3569a4, 16 operations, 2026-08-10) completed
    in a single turn with the summary "400 sections edited, rest untouched" and never
    paused. The threshold sits higher than 400 -- the docs' own example is 864 -- and
    chasing it would have cost the better part of the recording budget on a maybe.
    """
    c = base(
        "paused-large-edit",
        "A very large edit that applies what it can, keeps that work, and pauses with "
        "awaiting_kind continue_prompt to ask whether to carry on -- plus the 409 that "
        "rejects /approve on a pause that needs /continue.",
        "Reconstructed from /guides/async-jobs and /guides/streaming. A real "
        "400-section whole-document edit was recorded first (16 operations) and "
        "completed without pausing, so the pause itself could not be observed inside "
        "the recording budget. The real large edit is recorded separately as "
        "large-multi-section-edit; this cassette carries only the pause.",
        ["B-033", "B-034", "B-035", "B-036", "B-037", "B-038", "B-039", "B-059"],
    )
    job_id = "550e8400-e29b-41d4-a716-446655440000"  # the docs' own example id
    session = "sdmock-continue-001"

    paused_job = {
        "job_id": job_id,
        "session_id": session,
        "job_type": "chat",
        "status": "awaiting_approval",
        "progress": 58,
        "created_at": "2026-08-10T00:00:00Z",
        "updated_at": "2026-08-10T00:04:12Z",
        "metadata": {
            "awaiting_kind": "continue_prompt",
            "continue_prompt": {
                "message": "I've updated 500 of 864 sections so far. 364 remain. "
                           "Want me to continue with the rest?",
                "done": 500,
                "total": 864,
                "remaining": 364,
            },
        },
    }

    c.interactions.append(
        Interaction(
            id="i-001", transport="rest",
            request=RecordedRequest(
                method="GET", path=f"/v1/jobs/{job_id}",
                headers={"accept": "application/json"},
            ),
            response=RecordedResponse(
                status=200,
                headers={"content-type": "application/json"},
                json_body=paused_job,
            ),
            note="the pause: awaiting_kind is continue_prompt and there are NO "
                 "pending_changes (B-034)",
        )
    )
    c.interactions.append(
        Interaction(
            id="i-002", transport="rest",
            request=RecordedRequest(
                method="POST", path=f"/v1/chat/{session}/approve",
                headers={"content-type": "application/json"},
                json_body={"job_id": job_id, "approved": True},
            ),
            response=RecordedResponse(
                status=409,
                headers={"content-type": "application/json"},
                json_body={
                    "detail": "This job is paused on a continue prompt, not a change "
                              "review. Resume it with POST /v1/chat/{session_id}/"
                              "continue instead."
                },
            ),
            note="approve on a continue pause -> 409; branch on awaiting_kind first "
                 "(B-036)",
        )
    )
    c.interactions.append(
        Interaction(
            id="i-003", transport="rest",
            request=RecordedRequest(
                method="POST", path=f"/v1/chat/{session}/continue",
                headers={"content-type": "application/json"},
                json_body={"job_id": job_id, "continue": True},
            ),
            response=RecordedResponse(
                status=200,
                headers={"content-type": "application/json"},
                json_body={"job_id": job_id, "status": "in_progress",
                           "message": "Resuming with a fresh budget."},
            ),
            note="continue: true resumes; the job may pause again for the next "
                 "segment (B-038)",
        )
    )
    return c


def main() -> int:
    for build in (rate_limit, rate_limit_surge, paused_large_edit):
        cassette = build()
        path = cassette.save(CASSETTES)
        print(f"  {cassette.scenario:24s} synthesised -> {path.relative_to(ROOT)}")
    print("\nAll are marked synthesised: true, carry a note explaining why they could "
          "not be\nrecorded, and are skipped when the contract suite runs against "
          "--target live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
