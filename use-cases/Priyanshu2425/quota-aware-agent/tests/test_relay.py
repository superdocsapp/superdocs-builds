"""The relay seam: which endpoint, which retries, and the second ceiling.

The build can now reach SuperDocs two ways -- your own key straight to the
origin, or a shared relay that lends its key under a daily ration. Three things
had to be true for that to be worth having, and each one is a section below:

  * the precedence never sends your key somewhere you did not choose;
  * four different 429s arrive at the same line and three of them want
    different answers;
  * the ration is a second ceiling on the SAME question `budget.py` already
    answers, so it is planned against, not counted beside.
"""

import pytest

from quota_aware_agent.agent import QuotaAwareAgent, Step
from quota_aware_agent.budget import RELAY_RATION, BudgetGuard, Change
from quota_aware_agent.client import (BASE, RELAY_DAILY_OPS, HttpTransport,
                                      RationExhausted, RelayRefused, Response,
                                      SuperDocsClient, backoff_seconds,
                                      relay_charges_for, resolve,
                                      retry_after_seconds, retry_wait,
                                      stop_signal)
from quota_aware_agent.policy import Policy, StopReason
from tests.fake import FakeSuperDocs

RELAY = "https://relay.example.dev"


# -- 1. which endpoint, and with whose key ----------------------------------

def test_your_own_key_goes_to_the_origin_and_never_to_the_relay():
    """A security position, not a preference: a key of yours must not reach
    infrastructure somebody else operates and logs, even when relay credentials
    are also present and would otherwise be perfectly usable."""
    e = resolve({"SUPERDOCS_API_KEY": "sk_mine",
                 "RELAY_URL": RELAY, "RELAY_KEY": "pk_shared"})

    assert e.key == "sk_mine"
    assert e.base == BASE
    assert not e.using_relay
    assert e.daily_ration is None       # no second ceiling, so none described
    assert RELAY not in e.base


def test_an_empty_key_is_not_a_key():
    """`SUPERDOCS_API_KEY=` in a .env is how somebody says 'not this one'. Read
    as set, it would send an empty bearer token to the origin and answer 401."""
    e = resolve({"SUPERDOCS_API_KEY": "  ", "RELAY_URL": RELAY,
                 "RELAY_KEY": "pk_shared"})

    assert e.using_relay and e.key == "pk_shared"


def test_the_relay_base_is_the_url_plus_the_prefix_and_the_paths_do_not_move():
    e = resolve({"RELAY_URL": RELAY + "/", "RELAY_KEY": "pk_shared"})

    assert e.base == RELAY + "/v1/superdocs"
    assert e.using_relay and e.daily_ration == RELAY_DAILY_OPS


def test_a_base_url_override_only_applies_to_your_own_key():
    e = resolve({"SUPERDOCS_API_KEY": "sk_mine",
                 "SUPERDOCS_BASE_URL": "https://staging.example/"})
    assert e.base == "https://staging.example"


def test_with_nothing_set_the_error_names_both_routes():
    """An agent told only 'get a key' goes and gets a key it did not need."""
    with pytest.raises(RuntimeError) as e:
        resolve({})

    message = str(e.value)
    assert "SUPERDOCS_API_KEY" in message
    assert "RELAY_URL" in message and "RELAY_KEY" in message
    assert "signup" in message


# -- 2. the four 429s -------------------------------------------------------

def _resp(status, body, headers=None):
    return Response(status, body, headers or {})


def test_a_spent_ration_stops_rather_than_retrying():
    """`Retry-After` here counts down to 00:00 UTC. A client honouring it sleeps
    for hours and a client ignoring it spins; both are worse than saying so."""
    with pytest.raises(RationExhausted) as e:
        stop_signal(429, {"error": {"code": "budget_exhausted",
                                    "message": "daily ration spent"}},
                    {"Retry-After": "41230"})

    assert e.value.retry_after_s == 41230        # reported in full, never slept
    assert "SUPERDOCS_API_KEY" in str(e.value)   # and the fix is in the message
    assert "not billed" in str(e.value).lower()


def test_the_relays_rate_limiter_is_retried():
    wait = retry_wait(_resp(429, {"error": {"code": "rate_limited"}},
                            {"Retry-After": "7"}),
                      method="POST", path="/v1/chat/async", attempt=1)
    assert wait == 7.0


def test_superdocs_own_application_429_is_surfaced_not_spun_on():
    """`detail` plus a Retry-After is the monthly quota talking. This build's
    whole position is that the platform's own signal is authoritative."""
    assert retry_wait(_resp(429, {"detail": "monthly quota exceeded"},
                            {"Retry-After": "60"}),
                      method="POST", path="/v1/chat/async", attempt=1) is None


def test_an_infrastructure_429_is_retried_with_backoff():
    """Plain text, no Retry-After: something in front of SuperDocs, not
    SuperDocs. Nothing was billed, so repeating it is safe."""
    wait = retry_wait(_resp(429, {"raw": "429 Too Many Requests"}),
                      method="POST", path="/v1/chat/async", attempt=1)
    assert wait is not None and 0 < wait <= 60


def test_a_retry_after_is_capped_so_a_client_never_looks_hung():
    assert retry_after_seconds({"retry-after": "86400"}) == 60.0
    assert retry_after_seconds({"Retry-After": "not a number"}) is None
    assert retry_after_seconds({}) is None


def test_a_gateway_error_is_retried_on_a_poll_and_not_on_a_billable_post():
    """The one place this build departs from the blanket policy, and why: a 502
    can come from a gateway that had already passed the request upstream, so
    repeating a billable POST can pay twice and apply the same edit twice."""
    assert retry_wait(_resp(502, {"raw": "bad gateway"}),
                      method="GET", path="/v1/jobs/j1", attempt=1) is not None
    assert retry_wait(_resp(502, {"raw": "bad gateway"}),
                      method="POST", path="/v1/chat/async", attempt=1) is None


def test_the_refusals_that_are_never_retried_are_never_retried():
    for status in (400, 401, 403, 404, 413, 422):
        assert retry_wait(_resp(status, {"detail": "no"}),
                          method="GET", path="/v1/jobs/j1", attempt=1) is None


def test_a_relay_ceiling_refusal_names_the_ceiling_and_the_way_round_it():
    with pytest.raises(RelayRefused) as e:
        stop_signal(413, {"error": {"code": "payload_too_large"}}, {})
    assert "8 MB" in str(e.value) and "SUPERDOCS_API_KEY" in str(e.value)

    with pytest.raises(RelayRefused) as e:
        stop_signal(400, {"error": {"code": "input_too_long"}}, {})
    assert "24,000" in str(e.value)

    with pytest.raises(RelayRefused) as e:
        stop_signal(403, {"error": {"code": "forbidden_model"}}, {})
    assert "deepseek/deepseek-v4-flash" in str(e.value)


def test_an_upstream_error_is_not_mistaken_for_a_relay_one():
    """SuperDocs answers `detail`, the relay answers `error`. Branching on the
    shape rather than the prose is what makes this a rule and not a guess."""
    stop_signal(429, {"detail": "monthly quota exceeded"}, {"Retry-After": "60"})
    stop_signal(500, {"raw": "Internal Server Error"}, {})


def test_the_charged_paths_are_the_ones_the_relay_bills():
    assert relay_charges_for("/v1/chat/async")
    assert relay_charges_for("/v1/chat/sess-1/approve")
    for free in ("/v1/agents/whoami", "/v1/documents/upload",
                 "/v1/documents/export", "/v1/jobs/j1"):
        assert not relay_charges_for(free)


def test_backoff_grows_and_is_capped():
    waits = [backoff_seconds(n, rand=lambda lo, hi: 1.0) for n in range(1, 8)]
    assert waits[:5] == [1, 2, 4, 8, 16]
    assert max(waits) <= 60


# -- 3. the transport loop --------------------------------------------------

class _Scripted(HttpTransport):
    """A transport whose network is a list. Everything above `_send` -- which is
    all of the retry policy -- is the real code."""

    def __init__(self, responses, **kw):
        #: Every wait the policy asked for, in order. Recorded rather than
        #: taken, so the suite tests the schedule without living through it.
        self.slept: list[float] = []
        super().__init__("pk_test", base=RELAY + "/v1/superdocs",
                         sleep=self.slept.append, **kw)
        self._responses = list(responses)
        self.sent = 0

    def _send(self, method, path, **kw):
        self.sent += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_a_rate_limited_call_is_repeated_until_it_lands():
    t = _Scripted([_resp(429, {"error": {"code": "rate_limited"}}, {"Retry-After": "1"}),
                   _resp(429, {"error": {"code": "rate_limited"}}, {"Retry-After": "1"}),
                   _resp(200, {"status": "ok"})])

    r = t.request("POST", "/v1/chat/async", json={})

    assert r.status == 200 and t.sent == 3
    assert t.slept == [1.0, 1.0]


def test_a_spent_ration_is_not_repeated_even_once():
    t = _Scripted([_resp(429, {"error": {"code": "budget_exhausted"}},
                         {"Retry-After": "41230"})] * 5)

    with pytest.raises(RationExhausted):
        t.request("POST", "/v1/chat/async", json={})

    assert t.sent == 1 and t.slept == []


def test_the_attempt_budget_is_finite_and_the_last_answer_is_returned():
    t = _Scripted([_resp(429, {"raw": "slow down"})] * 5, attempts=5)

    r = t.request("GET", "/v1/jobs/j1")

    assert r.status == 429 and t.sent == 5 and len(t.slept) == 4


# -- 4. the ration as a second ceiling, inside the budget model -------------

def test_the_lower_ceiling_is_the_one_you_may_spend():
    g = BudgetGuard()
    g.seed_from_whoami(400)
    g.open_ration(12)

    assert g.remaining().ops == 12
    assert g.remaining().limited_by == RELAY_RATION
    # And it is an estimate, because nobody ever confirmed it -- the same
    # honesty the monthly number gets between calls.
    assert not g.remaining().authoritative
    assert "capped by" in str(g.remaining())


def test_a_generous_ration_changes_nothing():
    g = BudgetGuard()
    g.seed_from_whoami(3)
    g.open_ration(RELAY_DAILY_OPS)

    assert g.remaining().ops == 3
    assert g.remaining().authoritative
    assert g.remaining().limited_by == ""


def test_no_ration_means_nothing_is_described_that_is_not_there():
    g = BudgetGuard()
    g.seed_from_whoami(3)
    g.spend_ration(1)                    # a no-op on the direct path

    assert g.ration is None
    assert str(g.remaining()) == "3 operations (confirmed)"


def test_the_ration_is_counted_in_calls_not_in_operations():
    """SuperDocs bills one operation per 25 sections; a lender counts the calls
    it proxied. Deriving one from the other invents an accounting rule neither
    party uses."""
    g = BudgetGuard()
    g.seed_from_whoami(100)
    g.open_ration(3)
    g.reconcile(ops_charged=4, monthly_remaining=96, quota_exhausted=False)
    g.spend_ration(1)

    assert g.remaining().ops == 2        # the ration, down by ONE call
    assert g.ration.ops == 2


def test_a_spent_ration_refuses_to_start_and_says_which_ceiling_it_was():
    """The remedies differ. 'Buy more allowance' is the wrong advice when the
    account's allowance is untouched and it is the day's ration that is gone."""
    g = BudgetGuard()
    g.seed_from_whoami(400)
    g.open_ration(RELAY_DAILY_OPS)
    g.ration_exhausted()

    plan = g.fit([Change("a", 25)], batched=False)

    assert plan.publish == []
    assert "daily ration" in plan.rationale
    assert "allowance may well be untouched" in plan.rationale
    assert g.exhausted


def test_a_later_free_response_cannot_un_say_a_ration_refusal():
    g = BudgetGuard()
    g.seed_from_whoami(400)
    g.open_ration(RELAY_DAILY_OPS)
    g.ration_exhausted()
    g.reconcile(ops_charged=0, monthly_remaining=400, quota_exhausted=False)

    assert g.exhausted


def test_the_account_signal_keeps_its_own_explanation():
    g = BudgetGuard()
    g.open_ration(RELAY_DAILY_OPS)
    g.mark_exhausted()

    assert g.exhausted_because == "the allowance is exhausted"


# -- 5. and the agent plans against it --------------------------------------

class _RationedFake(FakeSuperDocs):
    """The fake, plus the one fact a relay transport carries that a direct one
    does not."""

    def __init__(self, ration: int, **kw):
        super().__init__(**kw)
        self.daily_ration = ration
        self.using_relay = True


def _agent(transport, **kw):
    return QuotaAwareAgent(SuperDocsClient(transport, sleep=lambda s: None), **kw)


def test_the_agent_sizes_work_to_the_ration_when_the_ration_is_lower():
    """500 operations of account allowance behind a ration of 2 is two steps of
    room. Planning 4 against the 500 is the exact failure this build exists to
    prevent, arriving through a number that was true about the wrong thing."""
    a = _agent(_RationedFake(ration=2, remaining=500), policy=Policy(reserve=0))
    a.read_allowance()

    plan = a.plan([Step(f"s{i}", "edit", 25) for i in range(4)])

    assert len(plan.publish) == 2
    assert [c.row_id for c in plan.defer] == ["s2", "s3"]


def test_the_budget_hint_names_the_second_ceiling_only_when_there_is_one():
    with_ration = _agent(_RationedFake(ration=5, remaining=500))
    with_ration.read_allowance()
    hint = with_ration.budget_hint()

    assert hint["remaining_operations"] == 5
    assert hint["daily_ration"]["remaining_calls"] == 5
    assert hint["daily_ration"]["binding"] is True

    direct = _agent(FakeSuperDocs(remaining=500))
    direct.read_allowance()
    assert "daily_ration" not in direct.budget_hint()


class _RefusesOnTheSecondEdit(_RationedFake):
    def request(self, method, path, **kw):
        if path == "/v1/chat/async" and self._edits >= 1:
            raise RationExhausted(
                429, {"error": {"code": "budget_exhausted"}},
                "the ration is spent; set SUPERDOCS_API_KEY or wait",
                retry_after_s=41230)
        return super().request(method, path, **kw)


def test_a_refused_ration_stops_the_run_and_is_not_confused_with_the_quota():
    """The relay refused before SuperDocs saw it, so nothing was billed by
    either — and the export still runs, because it is free on both sides."""
    fake = _RefusesOnTheSecondEdit(ration=RELAY_DAILY_OPS, remaining=500,
                                   sections_per_edit=25)
    a = _agent(fake, policy=Policy(reserve=0))

    report = a.run("s1", "doc.html", b"<p>x</p>",
                   [Step("a", "first", 25), Step("b", "second", 25)])

    assert report.stop_reason is StopReason.RATION_EXHAUSTED
    assert report.completed == ["a"] and report.deferred == ["b"]
    assert "set SUPERDOCS_API_KEY" in report.plain_language()
    assert "your own key" in report.stopped_because
    assert ("POST", "/v1/documents/export") in fake.calls


def test_a_refused_ration_leaves_the_step_repeatable_rather_than_in_doubt():
    """It was refused at the relay, so it cannot have been billed or applied —
    which is the one case where a rerun may safely send it again."""
    from quota_aware_agent.client import provably_never_sent

    assert provably_never_sent(
        RationExhausted(429, {"error": {"code": "budget_exhausted"}}, "x"))


# -- 6. two things that were only true once they were checked ---------------

def test_every_request_carries_a_named_user_agent(monkeypatch):
    """The relay sits behind Cloudflare, which answers the stdlib default
    `Python-urllib/3.x` with `403 error code: 1010` -- a bot block whose body is
    plain text and mentions neither a key nor a quota, so it reads exactly like
    a bad key and is not one. The relay path is dead on arrival without this.
    Verified against the live relay 2026-08-27."""
    import io
    import urllib.request

    from quota_aware_agent.client import USER_AGENT

    seen = {}

    class _Headers(dict):
        def get_content_type(self):
            return "application/json"

    class _Answer(io.BytesIO):
        status = 200
        headers = _Headers()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        seen["agent"] = req.get_header("User-agent")
        return _Answer(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    HttpTransport("pk_test", base=RELAY).request("GET", "/v1/agents/whoami")

    assert seen["agent"] == USER_AGENT
    assert "urllib" not in seen["agent"]


def test_the_dotenv_loader_does_not_reach_outside_this_build(tmp_path,
                                                             monkeypatch):
    """It used to walk six directories up, which is right for a build that owns
    its whole repository and wrong for one sitting beside other projects: the
    walk found a sibling's `.env` holding a real `sk_` key, and a `--live` run
    went to the origin on credentials it had never been given. The precedence
    rule exists to stop a key going where its owner did not send it, and a
    loader that hands one over underneath it defeats the rule from below."""
    import pathlib

    from quota_aware_agent import _load_dotenv

    build_root = pathlib.Path(
        __file__).resolve().parents[1]
    if (build_root / ".env").is_file():
        pytest.skip("this checkout has its own .env, which rightly wins")

    (tmp_path / "somebody_elses.env").write_text("")
    (tmp_path / ".env").write_text("SUPERDOCS_API_KEY=sk_not_yours\n")
    child = tmp_path / "nested" / "deeper"
    child.mkdir(parents=True)
    monkeypatch.chdir(child)
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)

    _load_dotenv()

    import os
    assert "SUPERDOCS_API_KEY" not in os.environ


def test_the_dotenv_loader_never_overrides_what_is_already_set(tmp_path,
                                                              monkeypatch):
    """So `export` still wins, and so a test that deliberately empties a
    variable to prove the no-credentials path stays emptied."""
    import os

    from quota_aware_agent import _read_env_file

    (tmp_path / ".env").write_text('RELAY_KEY="pk_from_the_file"\n'
                                   "SUPERDOCS_API_KEY=sk_from_the_file\n")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
    monkeypatch.delenv("RELAY_KEY", raising=False)

    _read_env_file(tmp_path / ".env")

    assert os.environ["SUPERDOCS_API_KEY"] == ""        # emptied stays emptied
    assert os.environ["RELAY_KEY"] == "pk_from_the_file"  # and quotes are shed


def test_the_balance_is_read_from_whichever_shape_whoami_answers_in():
    """The relay's SuperDocs key is NOT an agent account -- `whoami` through it
    answers `is_agent_account: false` and puts the balance in `quota.remaining`,
    not in `remaining_operations` and not in `usage.monthly_remaining`.

    A reader that knows only one of those names does not raise. It finds
    nothing, plans against zero, does nothing, and exits 0 — which is
    indistinguishable from an empty allowance and is the worst failure this
    build has, because it looks like a pass."""
    read = QuotaAwareAgent._balance_from_whoami

    # what the live relay and the live origin actually return, 2026-08-27
    assert read({"is_agent_account": False,
                 "quota": {"remaining": 500,
                           "resets_at": "2026-09-01T00:00:00+00:00"}}) == (
        500, "2026-09-01T00:00:00+00:00")
    # the flat form the docs name
    assert read({"remaining_operations": 42})[0] == 42
    # and the vocabulary every other response uses
    assert read({"usage": {"monthly_remaining": 7}})[0] == 7
    # nothing recognisable is None, never a number nobody stated
    assert read({"account_id": "x"}) == (None, "")


def test_an_unreadable_whoami_stops_the_run_out_loud():
    """Zero is only safe because it is never silent."""

    class _SaysNothingUseful(FakeSuperDocs):
        def request(self, method, path, **kw):
            r = super().request(method, path, **kw)
            if path == "/v1/agents/whoami":
                r.body.pop("quota", None)
            return r

    a = _agent(_SaysNothingUseful(remaining=500), policy=Policy(reserve=0))
    report = a.run("s1", "doc.html", b"<p>x</p>", [Step("a", "first", 25)])

    assert report.completed == []
    assert report.stop_reason is StopReason.NOTHING_FITS
    assert "no operations available to spend" in report.plain_language()
