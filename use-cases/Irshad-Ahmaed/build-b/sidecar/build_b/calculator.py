"""ROI calculator model and SuperDocs report generator for Build B.

Computes build-vs-buy TCO from user inputs, then generates a branded
PDF report via SuperDocs chat + export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import httpx
from build_a.client import SuperDocsClient, SuperDocsError  # noqa: E402

logger = logging.getLogger(__name__)

# --- TCO model constants (documented in README) ---

DEFAULT_MAINTENANCE_RATE = 0.20  # 20% of initial build hours per year
DEFAULT_INFRA_MONTHLY = 100.0    # $100/month cloud hosting estimate
DEFAULT_HORIZON_YEARS = 3        # 3-year comparison window


class SuperDocsTier(TypedDict):
    name: str
    monthly: float
    max_ops: int
    max_docs: int


SUPERDOCS_TIERS: list[SuperDocsTier] = [
    {"name": "Free", "monthly": 0.0, "max_ops": 500, "max_docs": 500},
    {"name": "Plus", "monthly": 20.0, "max_ops": 2000, "max_docs": 2000},
    {"name": "Pro", "monthly": 99.0, "max_ops": 10000, "max_docs": 10000},
]


@dataclass
class CalculatorInputs:
    """User inputs for the ROI calculator."""

    volume: int           # documents per month
    hours: float          # estimated engineering hours to build
    hourly_cost: float    # loaded hourly cost ($)
    maintenance_rate: float = DEFAULT_MAINTENANCE_RATE
    infrastructure_monthly: float = DEFAULT_INFRA_MONTHLY
    horizon_years: int = DEFAULT_HORIZON_YEARS


@dataclass
class CalculatorResults:
    """Computed TCO results."""

    build_one_time: float
    build_maintenance_annual: float
    build_infra_annual: float
    build_total: float
    buy_annual: float
    buy_total: float
    buy_tier: str
    savings: float
    payback_months: float | None
    inputs: CalculatorInputs


def compute_tco(inputs: CalculatorInputs) -> CalculatorResults:
    """Compute build-vs-buy TCO from user inputs.

    Build cost = (hours × hourly_cost) + (maintenance_rate × hours × hourly_cost × horizon)
                 + (infrastructure_monthly × 12 × horizon)
    Buy cost = SuperDocs tier annual cost × horizon
    """
    if inputs.horizon_years <= 0:
        raise ValueError("horizon_years must be positive")
    if inputs.volume < 0:
        raise ValueError("volume cannot be negative")
    if inputs.hours < 0:
        raise ValueError("hours cannot be negative")
    if inputs.hourly_cost < 0:
        raise ValueError("hourly_cost cannot be negative")
    if inputs.infrastructure_monthly < 0:
        raise ValueError("infrastructure_monthly cannot be negative")

    build_one_time = inputs.hours * inputs.hourly_cost
    build_maintenance_annual = (
        inputs.maintenance_rate * inputs.hours * inputs.hourly_cost
    )
    build_infra_annual = inputs.infrastructure_monthly * 12
    build_total = (
        build_one_time
        + build_maintenance_annual * inputs.horizon_years
        + build_infra_annual * inputs.horizon_years
    )

    # Select tier based on volume
    tier = SUPERDOCS_TIERS[0]
    for t in SUPERDOCS_TIERS:
        if inputs.volume <= t["max_docs"]:
            tier = t
            break
    else:
        tier = SUPERDOCS_TIERS[-1]

    buy_annual = tier["monthly"] * 12
    buy_total = buy_annual * inputs.horizon_years

    savings = build_total - buy_total

    # Payback: how many months for operating savings to recoup the build investment
    build_operating_annual = build_maintenance_annual + build_infra_annual
    buy_annual_operating = buy_annual
    annual_operating_savings = build_operating_annual - buy_annual_operating
    if tier["monthly"] > 0 and annual_operating_savings > 0:
        payback_months = int((build_one_time / annual_operating_savings) * 12)
    else:
        payback_months = None  # Free tier or build is cheaper to operate — no payback period

    return CalculatorResults(
        build_one_time=build_one_time,
        build_maintenance_annual=build_maintenance_annual,
        build_infra_annual=build_infra_annual,
        build_total=build_total,
        buy_annual=buy_annual,
        buy_total=buy_total,
        buy_tier=tier["name"],
        savings=savings,
        payback_months=payback_months,
        inputs=inputs,
    )


class ReportGenerator:
    """Generates a branded PDF report via SuperDocs chat + export."""

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    def build_report_prompt(self, results: CalculatorResults) -> str:
        """Build the exact prompt string with serialized computed values.

        KEY INVARIANT: the prompt contains the exact values from the
        calculator — never recompute server-side.
        """
        if results.savings > 0:
            payback_str = (
                f"Immediate (Day 1 — $0 CapEx). "
                f"In-house build break-even: {results.payback_months:.1f} months to recoup ${results.build_one_time:,.0f} initial dev cost"
                if results.payback_months is not None
                else "Immediate (Day 1 — $0 CapEx, Free Tier)"
            )
        else:
            payback_str = "N/A (in-house build is cheaper)"

        return (
            f"Generate a professional build-vs-buy comparison report. "
            f"Prepared for: Technology Leadership & Procurement. "
            f"Organization: Enterprise Decision Analysis. "
            f"Build cost: ${results.build_one_time:,.0f} (one-time) + "
            f"${results.build_maintenance_annual:,.0f}/year maintenance + "
            f"${results.build_infra_annual:,.0f}/year infrastructure. "
            f"Buy cost (SuperDocs {results.buy_tier} plan): "
            f"${results.buy_annual:,.0f}/year. "
            f"Total build cost over {results.inputs.horizon_years} years: "
            f"${results.build_total:,.0f}. "
            f"Total buy cost over {results.inputs.horizon_years} years: "
            f"${results.buy_total:,.0f}. "
            f"Savings: ${results.savings:,.0f}. "
            f"Payback period: {payback_str}. "
            f"Input assumptions: document volume={results.inputs.volume}/month, "
            f"engineering hours={results.inputs.hours}, "
            f"hourly cost=${results.inputs.hourly_cost}, "
            f"infrastructure=${results.inputs.infrastructure_monthly}/month, "
            f"horizon={results.inputs.horizon_years} years. "
            f"Do not include any 'Please fill:' or placeholder brackets in the report."
        )

    def build_report_template(self, results: CalculatorResults) -> str:
        """Build initial clean HTML report template for instant SuperDocs processing."""
        payback_str = (
            f"Immediate (Day 1 — $0 CapEx). In-house break-even: {results.payback_months:.1f} months"
            if results.payback_months is not None
            else "Immediate (Day 1 — $0 CapEx, Free Tier)"
        )
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Build vs Buy Financial Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.6; padding: 32px; max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #0f172a; font-size: 24px; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-bottom: 16px; }}
  h2 {{ color: #1e40af; font-size: 18px; margin-top: 24px; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  th, td {{ padding: 10px 14px; text-align: left; border: 1px solid #cbd5e1; font-size: 14px; }}
  th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
  .highlight {{ background: #f0fdf4; font-weight: bold; color: #15803d; }}
  .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; }}
  .badge-success {{ background: #dcfce7; color: #15803d; }}
</style>
</head>
<body>
  <h1>Build vs. Buy: Financial Comparison Report</h1>
  <div class="card">
    <p style="margin: 0; font-size: 13px; color: #64748b;">
      <strong>Prepared For:</strong> Technology Leadership & Procurement &nbsp;|&nbsp;
      <strong>Date:</strong> August 20, 2026 &nbsp;|&nbsp;
      <strong>Subject:</strong> SuperDocs {results.buy_tier} Acquisition Analysis
    </p>
  </div>

  <h2>1. Executive Summary</h2>
  <p>
    This report evaluates the Total Cost of Ownership (TCO) of developing an in-house document automation pipeline versus adopting <strong>SuperDocs {results.buy_tier}</strong>.
    Over a {results.inputs.horizon_years}-year horizon, choosing SuperDocs yields total projected net savings of <strong>${results.savings:,.0f}</strong>.
    The SaaS option requires <strong>$0 upfront CapEx</strong>, delivering positive cash flow from Day 1.
  </p>

  <h2>2. Financial Comparison ({results.inputs.horizon_years}-Year TCO)</h2>
  <table>
    <thead>
      <tr>
        <th>Cost Category</th>
        <th>Build In-House</th>
        <th>SuperDocs {results.buy_tier} (Buy)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Initial Development (CapEx)</td>
        <td>${results.build_one_time:,.0f}</td>
        <td>$0</td>
      </tr>
      <tr>
        <td>Annual Maintenance (20% of build)</td>
        <td>${results.build_maintenance_annual:,.0f} / year</td>
        <td>$0</td>
      </tr>
      <tr>
        <td>Annual Infrastructure</td>
        <td>${results.build_infra_annual:,.0f} / year</td>
        <td>Included</td>
      </tr>
      <tr class="highlight">
        <td>TOTAL {results.inputs.horizon_years}-YEAR EXPENDITURE</td>
        <td>${results.build_total:,.0f}</td>
        <td>${results.buy_total:,.0f}</td>
      </tr>
    </tbody>
  </table>

  <h2>3. Key Financial Outcomes</h2>
  <div class="card" style="display: flex; justify-content: space-between; text-align: center;">
    <div style="flex: 1;">
      <div style="font-size: 12px; color: #64748b;">TOTAL PROJECTED SAVINGS</div>
      <div style="font-size: 24px; font-weight: 700; color: #15803d;">${results.savings:,.0f}</div>
    </div>
    <div style="flex: 1;">
      <div style="font-size: 12px; color: #64748b;">SUPERDOCS PAYBACK</div>
      <div style="font-size: 20px; font-weight: 700; color: #0284c7;">Immediate (Day 1)</div>
    </div>
  </div>

  <h2>4. Recommendation</h2>
  <p>
    Procure the <strong>SuperDocs {results.buy_tier}</strong> plan to capitalize on the $0 CapEx requirement and eliminate ${results.build_one_time:,.0f} in custom development risk.
  </p>
</body>
</html>"""

    async def generate_report(
        self,
        session_id: str,
        results: CalculatorResults,
    ) -> str:
        """Send the pre-structured HTML report template to SuperDocs (fast export).

        Pre-seeding the template allows SuperDocs to process the document in ~1-2s
        instead of running a heavy 25s LLM generation cycle from scratch.
        """
        prompt = self.build_report_prompt(results)
        template_html = self.build_report_template(results)
        resp = await self.client.start_session(
            document_html=template_html,
            session_id=session_id,
            message=prompt,
        )
        if resp.document_changes and resp.document_changes.updated_html:
            return resp.document_changes.updated_html
        return resp.response or template_html

    async def export_report(
        self,
        session_id: str,
        output_path: Path,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = await self.client.export(session_id=session_id, format="pdf")
            if result.content:
                output_path.write_bytes(result.content)
                return output_path
            elif result.download_url:
                async with httpx.AsyncClient() as http:
                    resp = await http.get(result.download_url)
                    resp.raise_for_status()
                    output_path.write_bytes(resp.content)
                    return output_path
        except SuperDocsError:
            pass

        # Fallback: pre-signed URL
        dl = await self.client.request_download(session_id, format="pdf")
        async with httpx.AsyncClient() as http:
            resp = await http.get(dl.download_url)
            resp.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.content)
            return output_path
