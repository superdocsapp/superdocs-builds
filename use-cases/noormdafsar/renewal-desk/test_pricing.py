"""Tests for the deterministic half. No API key, no network, no SuperDocs.

Run:  python test_pricing.py

Every figure below is hand-checkable against data/pricing_policy.json. That is
the point: the prices in the customer-facing documents come from here, not from
a model, so they can be asserted rather than trusted.
"""

from pathlib import Path

from pricing import decide_all, money

HERE = Path(__file__).resolve().parent
FAILURES: list[str] = []


def check(name: str, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def main() -> int:
    decisions, accounts, policy = decide_all(HERE / "data")
    by = {d.account_id: d for d in decisions}

    # ---- 1. four drivers stack, under the 15% cap -------------------------
    # base 3 + seat overage 4 (311 active vs 250 contracted, +24%)
    #        + tier crossing 3 (910k -> 1.84M crosses 1M)
    #        + growth 4 (102% YoY) = 14%.  42.00 * 1.14 = 47.88
    a = by["ACM-1042"]
    check("ACM price", a.new_price, 47.88)
    check("ACM pct", a.change_pct, 14.0)
    check("ACM drivers", len(a.drivers), 4)
    check("ACM capped", a.capped, False)
    check("ACM gated", a.gated, True)

    # ---- 2. no tier crossing when already above the tier last year --------
    # base 3 + seat overage 4 (96 vs 80) + growth 4 (126%) = 11%, NOT 14%:
    # prior-year volume was already 1.15M so nothing was "crossed".
    b = by["BPA-3310"]
    check("BPA price", b.new_price, 49.95)
    check("BPA pct", b.change_pct, 11.0)
    check("BPA no tier-crossing driver",
          any("tier" in d.reason for d in b.drivers), False)

    # ---- 3. the quiet, healthy account gets the base adjustment only ------
    n = by["NWL-2087"]
    check("NWL price", n.new_price, 30.90)
    check("NWL drivers", len(n.drivers), 1)
    check("NWL gated", n.gated, False)

    # ---- 4. promo expiry, clamped by the 15% cap -------------------------
    # list rate is 43.75 but 35.00 * 1.15 = 40.25 wins.
    h = by["HLB-9114"]
    check("HLB price", h.new_price, 40.25)
    check("HLB capped", h.capped, True)
    check("HLB pct", h.change_pct, 15.0)

    # ---- 5. a decrease: volume band beats the annual adjustment ----------
    f = by["FMF-7742"]
    check("FMF price", f.new_price, 36.00)
    check("FMF direction", f.direction, "decrease")
    check("FMF seats", f.renewal_seats, 750)
    check("FMF gated", f.gated, False)   # decreases never hit the increase gate

    # ---- 6. a multi-year lock means no change at all ---------------------
    i = by["IWC-1201"]
    check("IWC price", i.new_price, 30.00)
    check("IWC direction", i.direction, "none")
    check("IWC gated", i.gated, False)

    # ---- 7. a small increase still gates on the churn-risk flag ----------
    # 3% and $2,073/yr are both under the numeric gates; the flag alone holds it.
    g = by["GSC-8830"]
    check("GSC pct", g.change_pct, 3.0)
    check("GSC gated", g.gated, True)
    check("GSC gate reason is the flag",
          any("churn_risk" in r for r in g.gate_reasons), True)

    # ---- 8. three different, named skip reasons --------------------------
    check("CHS skipped", by["CHS-0771"].action, "skip")
    check("CHS reason", "dispute" in by["CHS-0771"].skip_reason, True)
    check("DRM skipped", by["DRM-5518"].action, "skip")
    check("DRM reason", "missing" in by["DRM-5518"].skip_reason, True)
    check("EVR skipped", by["EVR-6205"].action, "skip")
    check("EVR reason", "window" in by["EVR-6205"].skip_reason, True)

    # ---- 9. nothing exceeds the policy cap, ever -------------------------
    cap = policy["caps"]["max_total_increase_pct"]
    for d in decisions:
        if d.action == "process" and d.change_pct > cap:
            FAILURES.append(f"{d.account_id} exceeded the {cap}% cap at {d.change_pct}%")

    # ---- 10. every processed account carries at least one named driver ----
    for d in decisions:
        if d.action == "process" and not d.drivers:
            FAILURES.append(f"{d.account_id} has a price with no named driver")

    # ---- 11. gated accounts are a strict subset, and non-trivial ---------
    gated = [d.account_id for d in decisions if d.gated]
    check("gated set", sorted(gated), ["ACM-1042", "BPA-3310", "GSC-8830", "HLB-9114"])

    print(f"{'account':<10} {'old':>8} {'new':>8} {'pct':>7}  {'gate':<6} drivers")
    print("-" * 78)
    for d in decisions:
        if d.action == "skip":
            print(f"{d.account_id:<10} {'-- skipped --':>25}  {d.skip_reason[:40]}")
            continue
        print(f"{d.account_id:<10} {money(d.current_price):>8} {money(d.new_price):>8} "
              f"{d.change_pct:>+6.1f}%  {'HUMAN' if d.gated else 'auto':<6} "
              f"{len(d.drivers)} driver(s)")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f_ in FAILURES:
            print(f"  - {f_}")
        return 1
    print("all pricing checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
