from typing import List, Tuple

from backend.app.schemas import Evidence, Citation
from backend.app.services.llm import LLMResponse

class CitationValidationService:
    """
    Dedicated component that validates evidence IDs cited by the LLM
    against the actual retrieved document chunks, rejecting any fabricated
    or incorrect references.
    """
    def validate_citations(
        self,
        llm_response: LLMResponse,
        retrieved_chunks: List[Evidence]
    ) -> Tuple[List[Citation], List[Evidence], List[Evidence]]:
        """
        Cross-references chunk IDs cited by the LLM against retrieved chunks.
        
        Returns:
            citations (List[Citation]): List of structured validated citations.
            supporting (List[Evidence]): Verified supporting evidence items.
            contradicting (List[Evidence]): Verified contradicting evidence items.
        """
        # Map retrieved chunks by chunk_id string for quick lookup
        retrieved_map = {str(chunk.chunk_id): chunk for chunk in retrieved_chunks}

        verified_citations: List[Citation] = []
        verified_supporting: List[Evidence] = []
        verified_contradicting: List[Evidence] = []

        # Validate supporting evidence citations
        for chunk_id in llm_response.supporting_evidence_ids:
            if chunk_id in retrieved_map:
                ev = retrieved_map[chunk_id]
                if ev not in verified_supporting:
                    verified_supporting.append(ev)
                
                # Construct citation record
                excerpt = ev.content[:150] + "..." if len(ev.content) > 150 else ev.content
                citation = Citation(
                    document_id=ev.document_id,
                    chunk_id=ev.chunk_id,
                    filename=ev.filename,
                    page_number=ev.page_number,
                    section=ev.section,
                    excerpt=excerpt
                )
                if citation not in verified_citations:
                    verified_citations.append(citation)

        # Validate contradicting evidence citations
        for chunk_id in llm_response.contradicting_evidence_ids:
            if chunk_id in retrieved_map:
                ev = retrieved_map[chunk_id]
                if ev not in verified_contradicting:
                    verified_contradicting.append(ev)
                
                # Construct citation record
                excerpt = ev.content[:150] + "..." if len(ev.content) > 150 else ev.content
                citation = Citation(
                    document_id=ev.document_id,
                    chunk_id=ev.chunk_id,
                    filename=ev.filename,
                    page_number=ev.page_number,
                    section=ev.section,
                    excerpt=excerpt
                )
                if citation not in verified_citations:
                    verified_citations.append(citation)

        return verified_citations, verified_supporting, verified_contradicting
