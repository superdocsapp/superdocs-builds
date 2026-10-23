"""Node: CompanyResearch — grounded structured company profile."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.agents.base import BaseNode
from app.agents.contracts import CompanyResearchInput, CompanyResearchOutput
from app.agents.state import BriefState
from app.database.session import AsyncSessionLocal
from app.models.document import Document
from app.schemas.document import DocumentSource
from app.services.company.company_research import CompanyResearchService
from app.services.rag.ingestion import IngestionService


class CompanyResearch(BaseNode[CompanyResearchInput, CompanyResearchOutput]):
    name = "CompanyResearch"
    input_model = CompanyResearchInput
    output_model = CompanyResearchOutput

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "company_name": state.get("company_name", ""),
            "company_url": state.get("company_url"),
        }

    async def execute(
        self,
        node_input: CompanyResearchInput,
        state: BriefState,
    ) -> CompanyResearchOutput:
        service = CompanyResearchService()
        profile = await service.research(node_input.company_name, node_input.company_url)
        profile_json = profile.model_dump()
        overview = profile.overview
        context = (
            f"Structured company research JSON:\n{profile.model_dump_json(indent=2)}\n\n"
            f"Sources: {', '.join(profile.sources) if profile.sources else 'none'}"
        )

        session_id = UUID(node_input.session_id)
        company_doc_id = uuid4()
        indexed_text = f"{overview}\n\n{context}"[:12000]

        async with AsyncSessionLocal() as db:
            db.add(
                Document(
                    id=company_doc_id,
                    session_id=session_id,
                    source=DocumentSource.COMPANY.value,
                    filename="company_research.json.txt",
                    content_text=overview,
                )
            )
            await db.flush()
            await IngestionService(db).index_document(
                session_id=session_id,
                document_id=company_doc_id,
                source=DocumentSource.COMPANY.value,
                text=indexed_text,
            )
            await db.commit()

        return CompanyResearchOutput(
            company_overview=overview,
            company_context=context,
            company_profile=profile_json,
        )

    def merge_output(
        self,
        state: BriefState,
        node_output: CompanyResearchOutput,
    ) -> BriefState:
        return {
            **state,
            "company_overview": node_output.company_overview,
            "company_context": node_output.company_context,
            "company_profile": node_output.company_profile,
        }


company_research = CompanyResearch()
