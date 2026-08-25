"""
LineageService: Constructs lineage graphs by traversing relationships.

This service builds comprehensive lineage graphs showing how claims trace back
through citations, evidence, knowledge entries, and reviews.
"""

from typing import List
from uuid import UUID

from backend.core.lineage.models import (
    LineageGraph, LineageNode, LineageEdge, KnowledgeProvenance
)
from backend.repositories.lineage import LineageLinkRepository
from backend.repositories.base import BaseRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


import re
import json

def _clean_text_preview(text: str, max_len: int = 50) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", str(text))
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean

def _format_claim_node_info(claim_type: str, content: str, source_stage: str = None):
    """Returns (node_type, clean_label, parsed_metadata)."""
    node_type = "claim"
    if claim_type == "memo_section" or (source_stage and "memo" in source_stage):
        node_type = "memo_section"

    if not content:
        label = claim_type.replace("_", " ").title() if claim_type else "Classification Claim"
        return node_type, label, {}

    trimmed = content.strip()
    if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
        try:
            data = json.loads(trimmed)
            if isinstance(data, dict):
                title = data.get("title") or data.get("section") or data.get("section_name")
                if title and not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", str(title), re.I):
                    return node_type, str(title), data

                sec_type = data.get("section_type")
                if sec_type:
                    return node_type, sec_type.replace("_", " ").title(), data

                field = data.get("field")
                if field:
                    return node_type, f"Finding: {field.replace('_', ' ').title()}", data

                desc = data.get("description") or data.get("summary")
                if desc:
                    return node_type, _clean_text_preview(str(desc)), data

                inner = data.get("new_html") or data.get("content") or data.get("content_preview")
                if inner and isinstance(inner, str):
                    preview = _clean_text_preview(inner)
                    if preview:
                        return node_type, preview, data
                return node_type, "Proposed Change", data
        except Exception:
            pass

    label = _clean_text_preview(content)
    if not label:
        label = claim_type.replace("_", " ").title() if claim_type else "Classification Claim"
    return node_type, label, {}


class LineageService:
    """Service for constructing lineage graphs"""

    def __init__(
        self,
        lineage_link_repo: LineageLinkRepository,
        claim_repo: BaseRepository,
        evidence_repo: BaseRepository,
        citation_repo: BaseRepository,
        knowledge_repo: BaseRepository,
        audit_repo: BaseRepository,
        stage_repo: BaseRepository,
        chunk_repo: BaseRepository,
        document_repo: BaseRepository,
        review_repo: BaseRepository,
    ):
        self.lineage_link_repo = lineage_link_repo
        self.claim_repo = claim_repo
        self.evidence_repo = evidence_repo
        self.citation_repo = citation_repo
        self.knowledge_repo = knowledge_repo
        self.audit_repo = audit_repo
        self.stage_repo = stage_repo
        self.chunk_repo = chunk_repo
        self.document_repo = document_repo
        self.review_repo = review_repo

    async def get_claim_lineage(
        self,
        claim_id: UUID,
        depth: int = 3
    ) -> LineageGraph:
        """
        Build lineage graph for a specific claim.

        Traverses relationships up to specified depth:
        - Claim → Citations → Evidence → Chunk → Document
        - Claim → LineageLinks (knowledge, regeneration)
        - Claim → Review

        Args:
            claim_id: The claim to build lineage for
            depth: How many relationship hops to traverse (default: 3)

        Returns:
            LineageGraph with all nodes and edges
        """
        logger.info("building_claim_lineage", claim_id=str(claim_id), depth=depth)

        nodes = []
        edges = []
        visited = set()

        # Get the claim
        claim = await self.claim_repo.get_by_id(claim_id)
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        # Add claim node
        node_type, clean_label, parsed_data = _format_claim_node_info(
            claim.claim_type, claim.content, claim.source_stage
        )
        claim_node = LineageNode(
            id=str(claim.id),
            type=node_type,
            label=clean_label,
            metadata={
                "status": claim.status,
                "source_stage": claim.source_stage,
                "claim_type": claim.claim_type,
                "workflow_run_id": str(claim.workflow_run_id),
                "summary": parsed_data.get("description") or parsed_data.get("summary"),
                "reasoning": parsed_data.get("analyst_reasoning") or parsed_data.get("ai_explanation"),
            }
        )
        nodes.append(claim_node)
        visited.add(str(claim.id))

        # Traverse citations (claim → evidence)
        if depth > 0:
            citations = await self.citation_repo.list_by_claim(claim.id)
            for citation in citations:
                evidence_id = str(citation.evidence_id)
                if evidence_id not in visited:
                    # Get evidence details
                    evidence = await self.evidence_repo.get_by_id(citation.evidence_id)
                    if evidence:
                        # Add evidence node
                        evidence_node = LineageNode(
                            id=evidence_id,
                            type="evidence",
                            label=evidence.extracted_text[:50] + "..." if len(evidence.extracted_text) > 50 else evidence.extracted_text,
                            metadata={
                                "relevance_score": evidence.relevance_score,
                                "evidence_type": evidence.evidence_type,
                                "page_number": evidence.page_number
                            }
                        )
                        nodes.append(evidence_node)
                        visited.add(evidence_id)

                        # Add citation edge
                        edges.append(LineageEdge(
                            source_id=str(claim.id),
                            target_id=evidence_id,
                            edge_type="cited_by",
                            metadata={"relevance_score": citation.relevance_score}
                        ))

                        # Traverse further: evidence → chunk → document
                        if depth > 1 and evidence.chunk_id:
                            chunk_id = str(evidence.chunk_id)
                            if chunk_id not in visited:
                                chunk = await self.chunk_repo.get_by_id(evidence.chunk_id)
                                if chunk:
                                    chunk_node = LineageNode(
                                        id=chunk_id,
                                        type="chunk",
                                        label=f"Chunk {chunk.chunk_index}",
                                        metadata={
                                            "chunk_index": chunk.chunk_index,
                                            "page_number": chunk.page_number
                                        }
                                    )
                                    nodes.append(chunk_node)
                                    visited.add(chunk_id)

                                    edges.append(LineageEdge(
                                        source_id=evidence_id,
                                        target_id=chunk_id,
                                        edge_type="extracted_from",
                                        metadata={}
                                    ))

                                    # Traverse further: chunk → document
                                    if depth > 2:
                                        document_id = str(chunk.document_id)
                                        if document_id not in visited:
                                            document = await self.document_repo.get_by_id(chunk.document_id)
                                            if document:
                                                document_node = LineageNode(
                                                    id=document_id,
                                                    type="document",
                                                    label=document.filename,
                                                    metadata={
                                                        "mime_type": document.mime_type,
                                                        "processing_status": document.processing_status
                                                    }
                                                )
                                                nodes.append(document_node)
                                                visited.add(document_id)

                                                edges.append(LineageEdge(
                                                    source_id=chunk_id,
                                                    target_id=document_id,
                                                    edge_type="from_document",
                                                    metadata={}
                                                ))

        # Traverse lineage_links (claim → knowledge, claim → claim)
        lineage_links = await self.lineage_link_repo.get_links_by_source("claim", claim.id)
        for link in lineage_links:
            target_id = str(link.target_id)
            if target_id not in visited:
                if link.target_type == "knowledge_entry":
                    knowledge = await self.knowledge_repo.get_by_id(link.target_id)
                    if knowledge:
                        nodes.append(LineageNode(
                            id=target_id,
                            type="knowledge",
                            label=knowledge.content[:50] + "..." if len(knowledge.content) > 50 else knowledge.content,
                            metadata={
                                "source_run_id": str(knowledge.source_run_id) if knowledge.source_run_id else None,
                                "workflow_type": knowledge.workflow_type
                            }
                        ))
                        visited.add(target_id)

                        edges.append(LineageEdge(
                            source_id=str(claim.id),
                            target_id=target_id,
                            edge_type="derived_from",
                            metadata=link.link_metadata or {}
                        ))

                elif link.target_type == "claim" and link.link_type == "regenerated_from":
                    # Handle regeneration links
                    prior_claim = await self.claim_repo.get_by_id(link.target_id)
                    if prior_claim:
                        nodes.append(LineageNode(
                            id=target_id,
                            type="claim",
                            label=f"[Previous] {prior_claim.content[:40]}...",
                            metadata={
                                "status": prior_claim.status,
                                "source_stage": prior_claim.source_stage,
                                "is_superseded": True
                            }
                        ))
                        visited.add(target_id)

                        edges.append(LineageEdge(
                            source_id=str(claim.id),
                            target_id=target_id,
                            edge_type="regenerated_from",
                            metadata=link.link_metadata or {}
                        ))

                elif link.target_type == "claim" and link.link_type == "reused_from_baseline":
                    # Handle baseline reuse links (Phase 7)
                    baseline_claim = await self.claim_repo.get_by_id(link.target_id)
                    if baseline_claim:
                        nodes.append(LineageNode(
                            id=target_id,
                            type="claim",
                            label=f"[Baseline] {baseline_claim.content[:40]}...",
                            metadata={
                                "status": baseline_claim.status,
                                "source_stage": baseline_claim.source_stage,
                                "is_baseline": True,
                                "content_hash": link.link_metadata.get("content_hash") if link.link_metadata else None
                            }
                        ))
                        visited.add(target_id)

                        edges.append(LineageEdge(
                            source_id=str(claim.id),
                            target_id=target_id,
                            edge_type="reused_from_baseline",
                            metadata=link.link_metadata or {}
                        ))

                elif link.target_type == "claim" and link.link_type in ("superseded_by", "contradicts"):
                    # Handle supersession and contradiction links (Phase 7)
                    related_claim = await self.claim_repo.get_by_id(link.target_id)
                    if related_claim:
                        nodes.append(LineageNode(
                            id=target_id,
                            type="claim",
                            label=f"[{link.link_type.replace('_', ' ').title()}] {related_claim.content[:40]}...",
                            metadata={
                                "status": related_claim.status,
                                "source_stage": related_claim.source_stage,
                                "relationship": link.link_type
                            }
                        ))
                        visited.add(target_id)

                        edges.append(LineageEdge(
                            source_id=str(claim.id),
                            target_id=target_id,
                            edge_type=link.link_type,
                            metadata=link.link_metadata or {}
                        ))

                elif link.target_type == "superdocs_change" and link.link_type == "superdocs_edit":
                    # Handle SuperDocs edit links (Phase 7)
                    nodes.append(LineageNode(
                        id=target_id,
                        type="superdocs_change",
                        label=f"SuperDocs Edit: {link.link_metadata.get('description', 'Change')[:40]}..." if link.link_metadata else "SuperDocs Edit",
                        metadata=link.link_metadata or {}
                    ))
                    visited.add(target_id)

                    edges.append(LineageEdge(
                        source_id=str(claim.id),
                        target_id=target_id,
                        edge_type="superdocs_edit",
                        metadata=link.link_metadata or {}
                    ))

        # Get review information (Claim.review_id is FK to one Review)
        if claim.review_id:
            review = await self.review_repo.get_by_id(claim.review_id)
            if review:
                review_id = str(review.id)
                if review_id not in visited:
                    nodes.append(LineageNode(
                        id=review_id,
                        type="review",
                        label=f"Review: {review.status}",
                        metadata={
                            "status": review.status,
                            "reviewer_id": review.reviewer_id,
                            "notes": review.notes
                        }
                    ))
                    visited.add(review_id)

                    edges.append(LineageEdge(
                        source_id=str(claim.id),
                        target_id=review_id,
                        edge_type="reviewed",
                        metadata={}
                    ))

        return LineageGraph(
            nodes=nodes,
            edges=edges,
            root_node_id=str(claim.id)
        )

    async def get_knowledge_provenance(
        self,
        claim_id: UUID
    ) -> List[KnowledgeProvenance]:
        """
        Retrieve all prior knowledge entries that influenced this claim.

        Returns structured provenance information showing:
        - What knowledge was reused
        - Where it came from
        - Why it was adopted

        Args:
            claim_id: The claim to get provenance for

        Returns:
            List of KnowledgeProvenance entries
        """
        logger.info("getting_knowledge_provenance", claim_id=str(claim_id))

        links = await self.lineage_link_repo.get_knowledge_links_for_claim(claim_id)
        provenance = []

        for link in links:
            knowledge = await self.knowledge_repo.get_by_id(link.target_id)
            if knowledge:
                provenance.append(KnowledgeProvenance(
                    knowledge_entry_id=knowledge.id,
                    source_run_id=knowledge.source_run_id,
                    content=knowledge.content,
                    relevance_score=link.link_metadata.get("relevance_score") if link.link_metadata else None,
                    adoption_reason=link.link_metadata.get("adoption_reason") if link.link_metadata else None,
                    created_at=knowledge.created_at.isoformat()
                ))

        return provenance

    async def get_regeneration_chain(self, claim_id: UUID) -> List:
        """
        Traverse regeneration history via lineage_links.

        Follows the chain of regeneration backwards from the current claim
        to the original, then returns in chronological order.

        Args:
            claim_id: The claim to get regeneration chain for

        Returns:
            List of claims from original to current
        """
        logger.info("getting_regeneration_chain", claim_id=str(claim_id))

        chain = []
        current_id = claim_id
        visited = set()

        # Walk backwards through regeneration links
        while current_id and current_id not in visited:
            visited.add(current_id)
            claim = await self.claim_repo.get_by_id(current_id)
            if claim:
                chain.insert(0, claim)  # Insert at beginning for chronological order

            # Find if this claim was regenerated from another
            links = await self.lineage_link_repo.get_links_by_source("claim", current_id)
            regeneration_link = next(
                (link for link in links if link.link_type == "regenerated_from"),
                None
            )

            if regeneration_link:
                current_id = regeneration_link.target_id
            else:
                break

        return chain

    async def get_run_lineage(self, run_id: UUID) -> LineageGraph:
        """
        Build lineage graph for entire workflow run (all claims).

        Retrieves all claims in the run and merges their lineage graphs
        into a single unified graph with multiple roots.

        Args:
            run_id: The workflow run to build lineage for

        Returns:
            LineageGraph with all claims and their provenance chains

        Raises:
            ValueError: If the workflow run is not found
        """
        logger.info("building_run_lineage", run_id=str(run_id))

        # Get all claims for this run
        claims = await self.claim_repo.list_by_run(run_id)
        if not claims:
            logger.warning("no_claims_found_for_run", run_id=str(run_id))
            return LineageGraph(nodes=[], edges=[], root_node_id=None)

        # Build lineage for each claim and merge
        all_nodes = {}  # Deduplicate by node ID
        all_edges = {}  # Deduplicate by (source_id, target_id, edge_type)

        for claim in claims:
            try:
                claim_graph = await self.get_claim_lineage(claim.id, depth=3)

                # Merge nodes
                for node in claim_graph.nodes:
                    if node.id not in all_nodes:
                        all_nodes[node.id] = node

                # Merge edges
                for edge in claim_graph.edges:
                    edge_key = (edge.source_id, edge.target_id, edge.edge_type)
                    if edge_key not in all_edges:
                        all_edges[edge_key] = edge

            except Exception as e:
                logger.error(
                    "failed_to_build_claim_lineage",
                    claim_id=str(claim.id),
                    error=str(e)
                )
                continue

        logger.info(
            "run_lineage_built",
            run_id=str(run_id),
            nodes=len(all_nodes),
            edges=len(all_edges),
            claims=len(claims)
        )

        return LineageGraph(
            nodes=list(all_nodes.values()),
            edges=list(all_edges.values()),
            root_node_id=None  # Multiple roots (one per claim)
        )
