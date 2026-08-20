import uuid

from app.schemas.freight_claim import (
    FreightClaimCreate,
    FreightClaim,
)


class FreightClaimService:
    def __init__(self):
        self.claims: dict[str, FreightClaim] = {}

    async def create_claim(
        self,
        data: FreightClaimCreate,
        session_id: str | None = None,
    ) -> FreightClaim:

        claim_id = str(uuid.uuid4())

        claim = FreightClaim(
            claim_id=claim_id,
            session_id=session_id or f"freight-claim-{uuid.uuid4()}",
            carrier=data.carrier,
            evidence=data.evidence,
            status="created",
        )

        self.claims[claim_id] = claim

        return claim

    async def get_claim(
        self,
        claim_id: str,
    ) -> FreightClaim | None:

        return self.claims.get(claim_id)

    async def get_by_session(
        self,
        session_id: str,
    ) -> FreightClaim | None:

        for claim in self.claims.values():
            if claim.session_id == session_id:
                return claim

        return None

    async def update_status(
        self,
        claim_id: str,
        status: str,
    ) -> FreightClaim | None:

        claim = self.claims.get(claim_id)

        if not claim:
            return None

        claim.status = status

        return claim
    async def update_claim(
    self,
    claim_id: str,
    **updates,
) -> FreightClaim | None:

        claim = self.claims.get(claim_id)

        if not claim:
            return None

        for key, value in updates.items():
            setattr(claim, key, value)

        return claim


freight_claim_service = FreightClaimService()