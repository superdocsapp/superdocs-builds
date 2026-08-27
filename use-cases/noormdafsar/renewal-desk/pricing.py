"""The deterministic half of Renewal Desk.

Every number in every document is computed here, in plain Python, from
data/pricing_policy.json. The AI's job is prose, never arithmetic: it receives
final figures as exact strings and is instructed to use them verbatim, and
verify.py-style checks in the pipeline confirm afterward that it did.

Output per account is a decision record:
    action   -- "process" | "skip"
    gated    -- True if a human must review before anything leaves the building
    drivers  -- the named reasons behind the price movement, for the notice
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


def money(x: float) -> str:
    return f"${x:,.2f}"


@dataclass
class Driver:
    reason: str
    pct: float | None = None       # None for absolute-band / lock / expiry drivers
    detail: str = ""


@dataclass
class Decision:
    account_id: str
    company: str
    action: str                    # process | skip
    skip_reason: str = ""
    gated: bool = False
    gate_reasons: list[str] = field(default_factory=list)
    direction: str = "none"        # increase | decrease | none
    current_price: float = 0.0
    new_price: float = 0.0
    change_pct: float = 0.0
    renewal_seats: int = 0
    current_annual: float = 0.0
    renewal_annual: float = 0.0
    price_delta_annual: float = 0.0   # price-driven only: (new-old) * seats * 12
    capped: bool = False
    drivers: list[Driver] = field(default_factory=list)

    def summary_sentence(self) -> str:
        """One factual sentence for the quote's adjustment summary."""
        if self.direction == "none":
            return (
                "No price change applies at this renewal: "
                + "; ".join(d.reason for d in self.drivers) + "."
            )
        verb = "increases" if self.direction == "increase" else "decreases"
        parts = []
        for d in self.drivers:
            parts.append(f"{d.reason}" + (f" (+{d.pct:g}%)" if d.pct else ""))
        s = (
            f"The per-seat price {verb} from {money(self.current_price)} to "
            f"{money(self.new_price)} ({self.change_pct:+.1f}%), reflecting: "
            + "; ".join(parts) + "."
        )
        if self.capped:
            s += " The total adjustment was capped by policy at 15%."
        return s


def load(data_dir: Path):
    accounts = json.loads((data_dir / "accounts.json").read_text(encoding="utf-8"))
    policy = json.loads((data_dir / "pricing_policy.json").read_text(encoding="utf-8"))
    return accounts, policy


def decide(acct: dict, policy: dict, today: date, window_days: int) -> Decision:
    d = Decision(account_id=acct["account_id"], company=acct["company"], action="process")

    # ---- skip rules: deliberate non-processing, each with a named reason ----
    for rule in policy["skip_rules"]:
        flag = rule.get("flag")
        if flag and flag in acct.get("flags", []):
            d.action, d.skip_reason = "skip", rule["reason"]
            return d
    renewal = date.fromisoformat(acct["renewal_date"])
    if (renewal - today).days > window_days:
        d.action = "skip"
        d.skip_reason = next(
            r["reason"] for r in policy["skip_rules"]
            if r.get("condition") == "renewal_outside_window"
        )
        return d

    # ---- renewal shape ----
    contracted = acct["seats_contracted"]
    active = acct.get("seats_active") or contracted
    d.renewal_seats = acct.get("committed_seats_next_term") or max(contracted, active)
    d.current_price = acct["current_price_per_seat"]
    d.current_annual = contracted * d.current_price * 12

    locked_until = acct.get("price_locked_until")
    promo = next((x for x in acct.get("discounts", []) if x.get("expires_at_renewal")), None)
    vb = policy["volume_band"]

    # ---- price: exactly one of four mutually exclusive paths ----
    if locked_until and date.fromisoformat(locked_until) > renewal:
        d.new_price = d.current_price
        d.drivers.append(Driver(policy["multi_year_lock"]["reason"],
                                detail=f"locked until {locked_until}"))
    elif (acct.get("committed_seats_next_term") or 0) >= vb["min_committed_seats"] \
            and acct.get("term_months", 12) >= vb["min_term_months"]:
        d.new_price = vb["price_per_seat"]
        d.drivers.append(Driver(vb["reason"],
                                detail=f"{d.renewal_seats} committed seats, "
                                       f"{acct['term_months']}-month term"))
    elif promo:
        target = promo["undiscounted_price"]
        cap = d.current_price * (1 + policy["caps"]["max_total_increase_pct"] / 100)
        d.new_price = round(min(target, cap), 2)
        d.capped = d.new_price < target
        d.drivers.append(Driver(policy["promo_expiry"]["reason"],
                                detail=f"list rate {money(target)}"))
        if d.capped:
            d.drivers.append(Driver(policy["caps"]["reason_when_capped"]))
    else:
        pct = policy["base_adjustment_pct"]
        d.drivers.append(Driver(policy["base_adjustment_reason"],
                                pct=policy["base_adjustment_pct"]))
        so = policy["seat_overage"]
        if active > contracted * (1 + so["threshold_pct"] / 100):
            pct += so["adjustment_pct"]
            d.drivers.append(Driver(so["reason"], pct=so["adjustment_pct"],
                                    detail=f"{active} active vs {contracted} contracted"))
        story = acct.get("usage_story") or {}
        tier = policy["usage_tier_crossing"]
        now_calls = story.get("api_calls_month_avg") or 0
        prior_calls = story.get("api_calls_prior_year_avg") or 0
        if prior_calls < tier["api_calls_tier"] <= now_calls:
            pct += tier["adjustment_pct"]
            d.drivers.append(Driver(tier["reason"], pct=tier["adjustment_pct"],
                                    detail=f"{prior_calls:,} -> {now_calls:,} calls/month"))
        growth = policy["usage_growth"]
        if prior_calls and (now_calls / prior_calls - 1) * 100 > growth["threshold_pct"]:
            pct += growth["adjustment_pct"]
            d.drivers.append(Driver(growth["reason"], pct=growth["adjustment_pct"],
                                    detail=f"{(now_calls / prior_calls - 1) * 100:.0f}% growth"))
        cap_pct = policy["caps"]["max_total_increase_pct"]
        if pct > cap_pct:
            pct, d.capped = cap_pct, True
            d.drivers.append(Driver(policy["caps"]["reason_when_capped"]))
        d.new_price = round(d.current_price * (1 + pct / 100), 2)

    # ---- derived figures ----
    d.change_pct = round((d.new_price / d.current_price - 1) * 100, 1)
    d.direction = ("increase" if d.new_price > d.current_price
                   else "decrease" if d.new_price < d.current_price else "none")
    d.renewal_annual = d.renewal_seats * d.new_price * 12
    d.price_delta_annual = round((d.new_price - d.current_price) * d.renewal_seats * 12, 2)

    # ---- the approval gate: who needs a human, and why ----
    gate = policy["approval_gate"]
    if d.direction == "increase" and d.change_pct > gate["increase_pct_above"]:
        d.gate_reasons.append(
            f"increase of {d.change_pct:.1f}% exceeds the {gate['increase_pct_above']:g}% gate")
    if d.direction == "increase" and d.price_delta_annual > gate["or_price_delta_annual_above_usd"]:
        d.gate_reasons.append(
            f"price-driven annual delta {money(d.price_delta_annual)} exceeds "
            f"{money(gate['or_price_delta_annual_above_usd'])}")
    flagged = [f for f in gate.get("or_flags", []) if f in acct.get("flags", [])]
    if flagged and d.direction != "none":
        d.gate_reasons.append(
            f"account carries the {'/'.join(flagged)} flag; any priced change is reviewed")
    d.gated = bool(d.gate_reasons)
    return d


def decide_all(data_dir: Path) -> tuple[list[Decision], dict, dict]:
    accounts, policy = load(data_dir)
    today = date.fromisoformat(accounts["batch"]["today"])
    window = accounts["batch"]["run_window_days"]
    decisions = [decide(a, policy, today, window) for a in accounts["accounts"]]
    return decisions, accounts, policy
