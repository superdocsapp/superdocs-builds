import uuid
from typing import List, Tuple
from app.helpers.text_extractor import extract_verbatim_quote
from app.schemas.assessment import GovernanceMetrics, FindingSchema
from app.schemas.enums import ESGPillar, FindingSeverity, SupplierTier


class GovernanceEvaluator:
    """Evaluates anti-corruption policies, whistleblower mechanisms, and sub-tier supply chain traceability."""

    @staticmethod
    def evaluate(raw_text: str, tier: str) -> Tuple[GovernanceMetrics, List[FindingSchema]]:
        lower_text = raw_text.lower()
        findings: List[FindingSchema] = []
        gov = GovernanceMetrics()

        # Anti-bribery policy
        if ("anti-bribery" in lower_text or "anti-corruption" in lower_text) and "informal" not in lower_text and "not documented" not in lower_text:
            gov.anti_bribery_policy = True
        else:
            gov.anti_bribery_policy = False

        # Whistleblower protection channel
        if "whistleblower" in lower_text or "anonymous hotline" in lower_text:
            gov.whistleblower_protection_channel = True

        # Sub-tier BOM traceability
        if "traceability" in lower_text or "bom" in lower_text or "chain of custody" in lower_text:
            gov.sub_tier_traceability = True

        # Gap Finding: Missing or informal anti-bribery policy
        if not gov.anti_bribery_policy:
            quote = extract_verbatim_quote(
                raw_text,
                ["bribery", "corruption", "informal", "not documented"],
                "Formal anti-corruption training is currently informal and not documented."
            )
            findings.append(FindingSchema(
                id=str(uuid.uuid4()),
                pillar=ESGPillar.GOVERNANCE,
                severity=FindingSeverity.HIGH,
                standard_clause="Clause 3.1: Mandatory Anti-Bribery Policy & Annual Training",
                shortfall_summary="Absence of formalized Anti-Bribery policy and audited staff training curriculum.",
                supplier_exact_quote=quote,
                source_location="Governance & Integrity Section",
                recommended_action="Adopt corporate Anti-Bribery Charter and submit certification of 100% staff completion within 45 days."
            ))

        return gov, findings
