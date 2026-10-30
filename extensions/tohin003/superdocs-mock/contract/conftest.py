"""Contract-suite configuration.

One suite, four combinations: {rest, mcp} x {mock, live}. The assertions are identical
across all four -- that identity is the whole point, and it is what turns a divergence
between the mock and the live service into a failing test rather than a surprise in
somebody's production.

    pytest                                   # mock, REST -- free, no key, the default
    pytest --transport mcp                   # mock, MCP  -- free, no key
    pytest --target live --allow-billing     # live, REST -- spends operations
    pytest --target live --transport mcp --allow-billing

The default posture is that a test run costs nothing. Spending is opt-in, stated at the
command line, and capped.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from support import (  # noqa: E402
    LIVE_BASE_URL,
    Api,
    Budget,
    BudgetExhausted,
    Journey,
    load_key,
)

BUDGET_DEFAULT = 25


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("sdmock")
    group.addoption(
        "--target", action="store", default="mock", choices=("mock", "live"),
        help="Run against the local mock (default, free, no key) or api.superdocs.app.",
    )
    group.addoption(
        "--transport", action="store", default="rest", choices=("rest", "mcp"),
        help="Drive the target over the REST API or the MCP server.",
    )
    group.addoption(
        "--allow-billing", action="store_true", default=False,
        help="Permit tests that spend SuperDocs operations. Required by --target live.",
    )
    group.addoption(
        "--op-budget", action="store", type=int, default=BUDGET_DEFAULT,
        help=f"Hard cap on billable operations for this run (default {BUDGET_DEFAULT}).",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "billable: spends SuperDocs operations")
    config.addinivalue_line("markers", "rest: REST transport only")
    config.addinivalue_line("markers", "mcp: MCP transport only")
    config.addinivalue_line("markers", "live_only: meaningless against the mock")
    config.addinivalue_line("markers", "mock_only: about the mock itself")
    config.addinivalue_line(
        "markers", "covers(*ids): behaviour-ledger rows this test asserts")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    target = config.getoption("--target")
    transport = config.getoption("--transport")
    billing = config.getoption("--allow-billing")

    skip_billing = pytest.mark.skip(
        reason="billable: spends operations; pass --allow-billing to run")
    skip_transport = pytest.mark.skip(reason=f"not applicable to --transport {transport}")
    skip_target = pytest.mark.skip(reason=f"not applicable to --target {target}")

    for item in items:
        if "billable" in item.keywords and target == "live" and not billing:
            item.add_marker(skip_billing)
        if "rest" in item.keywords and transport != "rest":
            item.add_marker(skip_transport)
        if "mcp" in item.keywords and transport != "mcp":
            item.add_marker(skip_transport)
        if "live_only" in item.keywords and target != "live":
            item.add_marker(skip_target)
        if "mock_only" in item.keywords and target != "mock":
            item.add_marker(skip_target)


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="session")
def target(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--target")


@pytest.fixture(scope="session")
def transport(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--transport")


@pytest.fixture(scope="session")
def budget(pytestconfig: pytest.Config) -> Budget:
    return Budget(limit=pytestconfig.getoption("--op-budget"))


@pytest.fixture(scope="session")
def base_url(target: str):
    """The address under test: a mock we start, or the live service."""
    if target == "live":
        yield LIVE_BASE_URL
        return
    from sdmock.testing import MockServer

    with MockServer() as server:
        yield server.url


@pytest.fixture(scope="session")
def api_key(target: str) -> str | None:
    key = load_key()
    if target == "live" and not key:
        pytest.skip(
            "--target live needs a key: put one in ~/.config/superdocs/api-key "
            "(chmod 600) or set SUPERDOCS_API_KEY"
        )
    return key


@pytest.fixture()
def api(base_url: str, target: str, transport: str, api_key, budget: Budget):
    client = Api(base_url, target=target, transport=transport, key=api_key,
                 budget=budget)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def journey(api: Api, target: str) -> Journey:
    # A fresh session id per live run so tests never inherit another run's document;
    # a stable one against the mock so replay stays deterministic.
    session = ("sdmock-review-001" if target == "mock"
               else f"sdmock-contract-{uuid.uuid4().hex[:12]}")
    return Journey(api=api, session_id=session, corpus=ROOT / "corpus")


@pytest.fixture(autouse=True)
def _rewind(api: Api, target: str):
    """Rewind mock cursors between tests so ordering never matters."""
    if target == "mock":
        api.client.post("/__sdmock__/reset")
    yield


def pytest_terminal_summary(terminalreporter, exitstatus, config: pytest.Config) -> None:
    budget = getattr(config, "_sdmock_budget", None)
    target = config.getoption("--target")
    if target == "live" and budget is not None:
        terminalreporter.write_sep(
            "-", f"operations spent: {budget.spent} of {budget.limit}"
        )
    if target != "live":
        return

    # A live run is the only evidence that the mock still tells the truth, and it is
    # perishable -- it is true of one day and one deployment. So it is written down,
    # dated, and committed, rather than reported in a message nobody can re-check.
    import datetime
    import json

    stats = terminalreporter.stats
    counts = {k: len(v) for k, v in stats.items() if k in
              {"passed", "failed", "error", "skipped", "xfailed", "xpassed"}}
    transport = config.getoption("--transport")
    today = datetime.date.today().isoformat()
    evidence = {
        "recorded_at": datetime.datetime.now(datetime.timezone.utc)
                       .replace(microsecond=0).isoformat(),
        "target": "https://api.superdocs.app",
        "transport": transport,
        "spec_pin": "ac0d44c3d031fd0e338e7e78839162904ee69e79",
        "results": counts,
        "exit_status": exitstatus,
        "operations_counted": budget.spent if budget else None,
        "operation_budget": budget.limit if budget else None,
        "note": "The contract suite, run unchanged against the live service. Assertions "
                "identical to the --target mock run; a divergence between the mock and "
                "SuperDocs would fail here.",
    }
    out = ROOT / "docs" / "evidence" / f"live-{transport}-{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    terminalreporter.write_sep("-", f"evidence written to {out.relative_to(ROOT)}")


def _measure_balance(key: str | None) -> int | None:
    """Read the account's true remaining balance. Free, and non-billable."""
    if not key:
        return None
    import httpx

    try:
        response = httpx.get(f"{LIVE_BASE_URL}/v1/users/me/promotions",
                             headers={"Authorization": f"Bearer {key}"}, timeout=30)
        active = response.json().get("active") or []
        return sum(int(p.get("ops_remaining") or 0) for p in active) if active else None
    except Exception:
        return None


@pytest.fixture(scope="session", autouse=True)
def _register_budget(pytestconfig: pytest.Config, budget: Budget, target: str, api_key):
    """Report what the run actually cost, not what it inferred.

    Counting from `usage` blocks under-reports: a review job left paused at
    awaiting_approval reports nothing until it completes, so a run that genuinely spent
    an operation can read zero. The balance is therefore measured directly, before and
    after, and both numbers are printed -- the inferred one because it is what the
    in-run guard enforces, the measured one because it is the truth.
    """
    pytestconfig._sdmock_budget = budget
    before = _measure_balance(api_key) if target == "live" else None
    yield
    if target != "live":
        return
    after = _measure_balance(api_key)
    print(f"\noperations counted during the run : {budget.spent} of {budget.limit}")
    if before is not None and after is not None:
        print(f"operations actually billed        : {before - after} "
              f"(promo balance {before} -> {after})")
