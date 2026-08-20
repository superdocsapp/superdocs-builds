import uuid

from app.schemas.email_contract import (
    EmailContract,
    EmailContractCreate,
)


class EmailContractService:
    def __init__(self):
        self.contracts: dict[str, EmailContract] = {}

    async def create_contract(
        self,
        data: EmailContractCreate,
    ) -> EmailContract:

        contract_id = str(uuid.uuid4())
        session_id = f"email-contract-{uuid.uuid4()}"

        contract = EmailContract(
            contract_id=contract_id,
            session_id=session_id,
            contract_type=data.contract_type,
            status="created",
        )

        self.contracts[contract_id] = contract

        return contract

    async def get_contract(
        self,
        contract_id: str,
    ) -> EmailContract | None:

        return self.contracts.get(contract_id)

    async def get_by_session(
        self,
        session_id: str,
    ) -> EmailContract | None:

        for contract in self.contracts.values():
            if contract.session_id == session_id:
                return contract

        return None


email_contract_service = EmailContractService()