"""
A synthetic, in-memory CRM. Per the task's own rule ("where your build needs a client, a company, or data,
invent them... real third-party data is not welcome"), every deal here is fictional. Shaped like a
minimal version of what a real CRM (Salesforce, HubSpot) API would return for a deal/opportunity record --
swapping this for a real CRM client later means implementing the same `get_deal(deal_id) -> Deal` interface
against a real API, nothing else in the pipeline needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Deal:
    deal_id: str
    client_company: str
    client_contact_name: str
    client_contact_email: str
    deal_value_usd: float
    product_name: str
    payment_terms: str
    contract_length_months: int
    sales_rep_name: str
    sales_rep_email: str
    notes: str = ""
    custom_fields: dict = field(default_factory=dict)


class FakeCRM:
    """In-memory CRM with a handful of fictional sample deals. Mirrors a real CRM client's shape
    (get_deal, list_deals) so swapping in a real Salesforce/HubSpot client is a drop-in replacement."""

    def __init__(self):
        self._deals: dict[str, Deal] = {
            "deal-001": Deal(
                deal_id="deal-001",
                client_company="Brightleaf Retail Co.",
                client_contact_name="Priya Nandakumar",
                client_contact_email="priya.nandakumar@brightleafretail.example",
                deal_value_usd=84000.0,
                product_name="Nimbus Analytics Platform — Enterprise Tier",
                payment_terms="Net 30, quarterly billing",
                contract_length_months=12,
                sales_rep_name="Meethu Mani Maran",
                sales_rep_email="meethu@example-vendor.com",
                notes="Client wants onboarding to start within 2 weeks of signature.",
            ),
            "deal-002": Deal(
                deal_id="deal-002",
                client_company="Coastal Fabrication LLC",
                client_contact_name="Daniel Osei",
                client_contact_email="d.osei@coastalfab.example",
                deal_value_usd=19500.0,
                product_name="Nimbus Analytics Platform — Starter Tier",
                payment_terms="Net 15, single annual invoice",
                contract_length_months=6,
                sales_rep_name="Meethu Mani Maran",
                sales_rep_email="meethu@example-vendor.com",
                notes="Price-sensitive; approved a 6-month pilot instead of annual commitment.",
            ),
        }

    def get_deal(self, deal_id: str) -> Optional[Deal]:
        return self._deals.get(deal_id)

    def list_deals(self) -> list[Deal]:
        return list(self._deals.values())
