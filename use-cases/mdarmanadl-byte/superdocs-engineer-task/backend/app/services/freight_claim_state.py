from typing import Any


class FreightClaimState:
    def __init__(self):
        self.claims: dict[str, dict[str, Any]] = {}

    def create(
        self,
        claim_id: str,
        session_id: str,
        carrier: str,
        evidence: list,
    ):
        claim = {
            "claim_id": claim_id,
            "session_id": session_id,
            "carrier": carrier,
            "evidence": evidence,
            "status": "uploaded",
            "job_id": None,
            "pending_changes": [],
            "claim_response": None,
            "packet_response": None,
            "chaser_response": None,
        }

        self.claims[claim_id] = claim

        return claim

    def get(self, claim_id: str):
        return self.claims.get(claim_id)

    def update(self, claim_id: str, **values):
        claim = self.claims.get(claim_id)

        if not claim:
            return None

        claim.update(values)

        return claim


freight_claim_state = FreightClaimState()