"""Group, total, and check.

Three jobs, in order.

**Supersede.** When two loss runs cover the same policy year, the later
valuation wins — but the difference is recorded as a conflict rather than
quietly overwritten. On a real account this is the whole game: reserves develop,
runs get reissued, and the same claim carries two very different numbers. Both
are correct as of their valuation date. Picking one silently is making an
underwriting decision without telling anyone.

**Aggregate.** Claim counts and incurred totals by policy year, open claims
separated out. Pure arithmetic over parsed rows.

**Examine.** The eight checklist rules. Each produces a finding or an explicit
pass, and a clean corpus is allowed to produce nothing at all.
"""

from __future__ import annotations

import os
import re
from datetime import date

from .model import Claim, Conflict, Finding, LossRun, Summary, YearSummary

SEVERITY_THRESHOLD = 100_000.00
STALE_MONTHS = 36
DORMANT_MONTHS = 24
LOSS_RATIO_REFERRAL = 0.60


# ---------------------------------------------------------------------------
# supersession
# ---------------------------------------------------------------------------

def choose_authoritative(runs: list[LossRun]) -> tuple[dict[int, LossRun], list[LossRun], list[Conflict]]:
    by_year: dict[int, list[LossRun]] = {}
    for r in runs:
        by_year.setdefault(r.policy_year, []).append(r)

    authoritative: dict[int, LossRun] = {}
    superseded: list[LossRun] = []
    conflicts: list[Conflict] = []

    for year, group in sorted(by_year.items()):
        group.sort(key=lambda r: (r.valuation_date or "", r.is_reissue))
        winner = group[-1]
        authoritative[year] = winner
        for loser in group[:-1]:
            superseded.append(loser)
            conflicts.extend(_diff_runs(loser, winner))

    return authoritative, superseded, conflicts


def _diff_runs(old: LossRun, new: LossRun) -> list[Conflict]:
    out: list[Conflict] = []
    old_by = {c.claim_no: c for c in old.claims}
    new_by = {c.claim_no: c for c in new.claims}

    for claim_no in sorted(set(old_by) | set(new_by)):
        a, b = old_by.get(claim_no), new_by.get(claim_no)
        if a is None:
            out.append(Conflict(
                kind="claim_added",
                subject=claim_no,
                left=f"absent from {old.label}",
                right=f"{b.incurred:,.2f} incurred in {new.label}",
                detail=(f"Reported {b.date_reported}, after the earlier run was "
                        f"valued {old.valuation_date}."),
                consequence="Earlier totals for this policy year understate it.",
            ))
            continue
        if b is None:
            out.append(Conflict(
                kind="claim_removed", subject=claim_no,
                left=f"present in {old.label}", right=f"absent from {new.label}",
                detail="Present on the superseded run and not on the later one.",
                consequence="Query with the carrier before relying on either total.",
            ))
            continue
        if abs(a.incurred - b.incurred) >= 0.01:
            delta = b.incurred - a.incurred
            out.append(Conflict(
                kind="incurred_changed", subject=claim_no,
                left=f"{a.incurred:,.2f} ({old.label})",
                right=f"{b.incurred:,.2f} ({new.label})",
                detail=(f"Moved {delta:+,.2f}. Paid {a.paid:,.2f} to "
                        f"{b.paid:,.2f}; reserve {a.reserve:,.2f} to "
                        f"{b.reserve:,.2f}."),
                consequence="Both figures are correct at their valuation date.",
            ))
        if a.status != b.status:
            out.append(Conflict(
                kind="status_changed", subject=claim_no,
                left=f"{a.status} ({old.label})", right=f"{b.status} ({new.label})",
                detail="Claim status differs between valuations.",
            ))
    return out


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def summarise(runs: list[LossRun], insured: str) -> Summary:
    authoritative, superseded, conflicts = choose_authoritative(runs)
    s = Summary(insured=insured, conflicts=conflicts)
    s.documents_read = [os.path.basename(r.path) for r in runs]
    s.documents_superseded = [os.path.basename(r.path) for r in superseded]

    for year, run in sorted(authoritative.items()):
        claims = run.claims
        open_claims = [c for c in claims if c.is_open]
        s.open_claims.extend(open_claims)
        s.years.append(YearSummary(
            policy_year=year,
            policy_no=run.policy_no,
            claim_count=len(claims),
            open_count=len(open_claims),
            total_paid=round(sum(c.paid for c in claims), 2),
            total_reserve=round(sum(c.reserve for c in claims), 2),
            total_incurred=round(sum(c.incurred for c in claims), 2),
            open_incurred=round(sum(c.incurred for c in open_claims), 2),
            earned_premium=run.earned_premium,
            source=run.label,
        ))
        if run.earned_premium is None:
            s.unverified.append(
                f"PY{year}: no earned premium on the loss run, so no loss ratio "
                f"could be calculated.")

    s.open_claims.sort(key=lambda c: -c.incurred)
    return s


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

def examine(summary: Summary, runs: list[LossRun], notes: dict[str, str],
            application_text: str = "", as_of: date | None = None) -> Summary:
    as_of = as_of or date.today()
    authoritative, superseded, _ = choose_authoritative(runs)
    live = [c for r in authoritative.values() for c in r.claims]
    f = summary.findings

    # R1 severity claims need an adjuster note
    noted = set(notes)
    for c in sorted(live, key=lambda c: -c.incurred):
        if c.incurred >= SEVERITY_THRESHOLD and c.claim_no not in noted:
            f.append(Finding("R1", "Severity claim without an adjuster note",
                             c.claim_no,
                             f"{c.incurred:,.2f} incurred, status {c.status}. "
                             f"No note in the file, so severity cannot be "
                             f"evaluated.", c.source.cite()))

    # R2 stale open claims / R6 dormant reserves
    for c in live:
        if not c.is_open:
            continue
        months = c.months_open(as_of)
        if months > STALE_MONTHS:
            f.append(Finding("R2", "Open more than 36 months", c.claim_no,
                             f"Open {months} months from date of loss "
                             f"{c.date_of_loss}. Incurred {c.incurred:,.2f}.",
                             c.source.cite()))
        if c.paid == 0 and c.reserve > 0 and months > DORMANT_MONTHS:
            f.append(Finding("R6", "Dormant reserve", c.claim_no,
                             f"Nothing paid against a reserve of "
                             f"{c.reserve:,.2f} after {months} months.",
                             c.source.cite()))

    # R3 loss ratio referral
    for y in summary.years:
        lr = y.loss_ratio
        if lr is not None and lr > LOSS_RATIO_REFERRAL:
            f.append(Finding("R3", "Loss ratio above referral threshold",
                             f"PY{y.policy_year}",
                             f"{lr:.1%} ({y.total_incurred:,.2f} incurred "
                             f"against {y.earned_premium:,.2f} earned).",
                             y.source))

    # R4 date of loss outside the policy period
    for run in authoritative.values():
        if not (run.period_start and run.period_end):
            continue
        for c in run.claims:
            if not c.date_of_loss:
                continue
            if not (run.period_start <= c.date_of_loss < run.period_end):
                f.append(Finding("R4", "Date of loss outside the policy period",
                                 c.claim_no,
                                 f"Loss dated {c.date_of_loss} filed under a "
                                 f"policy running {run.period_start} to "
                                 f"{run.period_end}.", c.source.cite()))

    # R5 application consistency
    f.extend(_check_application(application_text, live))

    # R7 duplicate claims
    # Date and amount alone are not evidence: a fleet can genuinely take four
    # identical windscreen losses on one day. A duplicate is the same event
    # described twice, so the descriptions have to agree as well.
    seen: dict[tuple, list[Claim]] = {}
    for c in live:
        seen.setdefault((c.date_of_loss, round(c.incurred, 2)), []).append(c)
    for key, group in seen.items():
        if len(group) < 2 or not key[0]:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                shared = _shared_terms(a.description, b.description)
                if len(shared) < 3:
                    continue
                f.append(Finding("R7", "Possible duplicate claim",
                                 f"{a.claim_no}, {b.claim_no}",
                                 f"Same date of loss {key[0]}, identical "
                                 f"incurred {key[1]:,.2f}, and overlapping "
                                 f"descriptions ({', '.join(sorted(shared)[:5])}). "
                                 f"Totals for this policy year may "
                                 f"double-count {key[1]:,.2f}.",
                                 a.source.cite()))

    # R8 loss run internal consistency  (checked on every run, superseded too)
    for run in runs:
        if run.stated_total is None:
            continue
        diff = round(run.stated_total - run.summed_total, 2)
        if abs(diff) >= 0.01:
            f.append(Finding("R8", "Loss run does not add up", run.label,
                             f"States {run.stated_total:,.2f} total incurred; "
                             f"rows sum to {run.summed_total:,.2f}, a "
                             f"difference of {diff:,.2f}.",
                             os.path.basename(run.path)))
        if run.stated_count is not None and run.stated_count != len(run.claims):
            f.append(Finding("R8", "Loss run claim count disagrees", run.label,
                             f"States {run.stated_count} claims; "
                             f"{len(run.claims)} rows present.",
                             os.path.basename(run.path)))

    return summary


def _check_application(text: str, live: list[Claim]) -> list[Finding]:
    """Compare what the applicant declared against what the runs show.

    Reads the specific declarations this checklist cares about. Where a
    declaration is not found, nothing is asserted about it -- an absent
    statement is not a false one.
    """
    out: list[Finding] = []
    if not text:
        return out
    src = "renewal application"

    m = re.search(r"(\d+)\s+claims?\s+exceeding\s+\$?([\d,]+)", text, re.I)
    if m:
        declared, threshold = int(m.group(1)), float(m.group(2).replace(",", ""))
        actual = [c for c in live if c.incurred > threshold]
        if len(actual) != declared:
            out.append(Finding(
                "R5", "Application understates claim count", "declaration",
                f"Application states {declared} claims exceeding "
                f"{threshold:,.0f}; the loss runs show {len(actual)}: "
                f"{', '.join(sorted(c.claim_no for c in actual))}.", src))

    m2 = re.search(r"no\s+(?:open\s+)?claim[^.]{0,40}?exceeds?\s+\$?([\d,]+)",
                   text, re.I)
    if m2:
        threshold = float(m2.group(1).replace(",", ""))
        actual = [c for c in live if c.is_open and c.incurred > threshold]
        if actual:
            out.append(Finding(
                "R5", "Application contradicted on open severity", "declaration",
                f"Application states no open claim exceeds {threshold:,.0f}; "
                f"{len(actual)} do: "
                f"{', '.join(sorted(c.claim_no for c in actual))}.", src))

    m3 = re.search(r"all claims from policy years?\s+(\d{4})\s+and\s+(\d{4})\s+are closed",
                   text, re.I)
    if m3:
        years = {int(m3.group(1)), int(m3.group(2))}
        still_open = [c for c in live if c.policy_year in years and c.is_open]
        if still_open:
            out.append(Finding(
                "R5", "Application contradicted on closed years", "declaration",
                f"Application states all {m3.group(1)}/{m3.group(2)} claims are "
                f"closed; {len(still_open)} remain open: "
                f"{', '.join(sorted(c.claim_no for c in still_open))}.", src))
    return out


STOPWORDS = {"from", "with", "that", "this", "were", "have", "been", "damage",
             "claim", "loss", "the", "and", "for"}


def _shared_terms(a: str, b: str) -> set[str]:
    """Meaningful words two descriptions have in common."""
    def toks(s: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower())
                if len(w) > 2 and w not in STOPWORDS}
    return toks(a) & toks(b)
