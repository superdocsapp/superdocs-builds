"""Semantic document-to-checklist matcher surviving messy/inconsistent filenames."""

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from core.enums import ExecutionStatus, MatchConfidence
from core.models import ChecklistItem, ClosingChecklist, DocumentMetadata, MatchResult


class SemanticMatcher:
    """Matches ingested transaction documents to closing checklist lines by content rather than filename."""

    LEGAL_STOPWORDS = {
        "the", "and", "or", "of", "in", "to", "a", "an", "for", "by", "with",
        "as", "at", "from", "on", "that", "this", "is", "are", "be", "all",
        "any", "each", "shall", "hereby", "herein", "hereto", "thereof", "therein",
        "section", "article", "page", "schedule", "exhibit", "tab", "document",
    }

    DOCUMENT_TYPE_SYNONYMS = {
        "merger agreement": {"agreement and plan of merger", "merger agreement", "plan of merger", "merger agmt"},
        "stock purchase agreement": {"stock purchase agreement", "share purchase agreement", "spa"},
        "asset purchase agreement": {"asset purchase agreement", "apa"},
        "escrow agreement": {"escrow agreement", "indemnification escrow agreement"},
        "transition services agreement": {"transition services agreement", "tsa"},
        "non-competition agreement": {"non-competition and non-solicitation agreement", "restrictive covenant agreement", "non-compete"},
        "ip assignment": {"intellectual property assignment agreement", "patent assignment", "ip transfer agreement"},
        "voting agreement": {"voting and support agreement", "voting agreement", "stockholder support agreement"},
        "bylaws": {"amended and restated bylaws", "corporate bylaws", "company bylaws"},
        "certificate of incorporation": {"amended and restated certificate of incorporation", "charter", "articles of incorporation"},
        "good standing": {"certificate of good standing", "good standing certificate", "delaware good standing"},
        "secretary certificate": {"secretary's certificate", "secretary certificate", "incumbency certificate", "officer incumbency"},
        "officer certificate": {"officer's closing certificate", "officer certificate", "closing certificate"},
        "solvency certificate": {"solvency certificate", "certificate of solvency"},
        "legal opinion": {"legal opinion of counsel", "opinion of counsel", "closing opinion"},
        "funds flow": {"funds flow memorandum", "closing flow of funds", "funds flow memo"},
        "payoff letter": {"payoff letter", "debt payoff agreement", "credit facility payoff"},
        "board consent": {"unanimous written consent of the board of directors", "board resolutions", "board of directors consent"},
        "shareholder consent": {"written consent of stockholders", "stockholder consent", "shareholder written consent"},
    }

    def __init__(self, high_threshold: float = 0.60, medium_threshold: float = 0.40):
        self.high_threshold = high_threshold
        self.medium_threshold = medium_threshold

    def match_pile(
        self,
        checklist: ClosingChecklist,
        documents: List[DocumentMetadata],
    ) -> List[MatchResult]:
        """Matches a collection of ingested documents against a full closing checklist."""
        results: List[MatchResult] = []
        doc_pool = {doc.doc_id: doc for doc in documents}
        
        compat_matrix: Dict[str, Dict[str, Tuple[float, List[str]]]] = {}
        for item in checklist.items:
            compat_matrix[item.item_id] = {}
            for doc_id, doc in doc_pool.items():
                score, reasons = self.score_match(item, doc)
                compat_matrix[item.item_id][doc_id] = (score, reasons)

        assigned_docs: Set[str] = set()
        
        for item in checklist.items:
            best_doc_id = None
            best_score = -1.0
            best_reasons = []

            for doc_id, (score, reasons) in compat_matrix[item.item_id].items():
                if doc_id in assigned_docs:
                    continue
                if score > best_score:
                    best_score = score
                    best_doc_id = doc_id
                    best_reasons = reasons

            if best_doc_id and best_score >= self.medium_threshold:
                assigned_docs.add(best_doc_id)
                matched_doc = doc_pool[best_doc_id]
                
                conf = (
                    MatchConfidence.HIGH
                    if best_score >= self.high_threshold
                    else MatchConfidence.MEDIUM
                )
                
                flags = []
                if item.signatures_required and matched_doc.execution_status == ExecutionStatus.UNSIGNED_DRAFT:
                    flags.append("Document is an unsigned draft with placeholder signature lines.")
                elif item.signatures_required and matched_doc.execution_status == ExecutionStatus.PARTIALLY_EXECUTED:
                    missing_signers = [b.party_name for b in matched_doc.signature_blocks if not b.is_signed]
                    flags.append(f"Missing execution by: {', '.join(missing_signers)}")

                results.append(
                    MatchResult(
                        checklist_item_id=item.item_id,
                        tab_number=item.tab_number,
                        doc_id=best_doc_id,
                        matched_filename=matched_doc.original_filename,
                        confidence=conf,
                        score=round(best_score, 3),
                        match_reasons=best_reasons,
                        execution_status=matched_doc.execution_status,
                        unresolved_flags=flags,
                    )
                )
            else:
                results.append(
                    MatchResult(
                        checklist_item_id=item.item_id,
                        tab_number=item.tab_number,
                        doc_id=None,
                        matched_filename=None,
                        confidence=MatchConfidence.UNMATCHED,
                        score=0.0,
                        match_reasons=["No matching document found in the uploaded file bundle."],
                        execution_status=ExecutionStatus.MISSING,
                        unresolved_flags=["Missing deliverable on closing checklist."],
                    )
                )

        return results

    def score_match(self, item: ChecklistItem, doc: DocumentMetadata) -> Tuple[float, List[str]]:
        """Calculates multi-signal semantic compatibility score between checklist item and document."""
        reasons = []
        weights = {
            "title_similarity": 0.40,
            "party_alignment": 0.20,
            "content_tfidf": 0.25,
            "category_affinity": 0.15,
        }

        title_score = self._score_title_similarity(item.title, doc.detected_title or "", doc.raw_text[:2000])
        if title_score > 0.6:
            reasons.append(f"Strong title & header match with '{doc.detected_title}' ({title_score:.2f})")

        party_score = self._score_parties(item.required_parties, doc.detected_parties, doc.raw_text[:3000])
        if party_score > 0.5:
            reasons.append(f"Matching entity/party signatures ({party_score:.2f})")

        target_text = f"{item.title} {item.description or ''} {item.category.value}"
        content_score = self._score_content_overlap(target_text, doc.raw_text)
        if content_score > 0.4:
            reasons.append(f"High semantic keyword overlap ({content_score:.2f})")

        cat_score = self._score_category_affinity(item.category.value, doc.raw_text)

        total_score = (
            weights["title_similarity"] * title_score
            + weights["party_alignment"] * party_score
            + weights["content_tfidf"] * content_score
            + weights["category_affinity"] * cat_score
        )

        return min(1.0, total_score), reasons

    def _score_title_similarity(self, checklist_title: str, detected_title: str, preamble_text: str) -> float:
        c_clean = self._clean_legal_text(checklist_title)
        d_clean = self._clean_legal_text(detected_title)

        if not c_clean or not d_clean:
            return 0.0

        if c_clean == d_clean:
            return 1.0

        for standard_term, syn_set in self.DOCUMENT_TYPE_SYNONYMS.items():
            if any(syn in c_clean for syn in syn_set) and any(syn in d_clean for syn in syn_set):
                return 0.95
            if any(syn in c_clean for syn in syn_set) and any(syn in preamble_text.lower() for syn in syn_set):
                return 0.85

        c_tokens = set(c_clean.split()) - self.LEGAL_STOPWORDS
        d_tokens = set(d_clean.split()) - self.LEGAL_STOPWORDS

        if not c_tokens or not d_tokens:
            return 0.0

        intersection = len(c_tokens & d_tokens)
        union = len(c_tokens | d_tokens)
        jaccard = intersection / union if union > 0 else 0.0

        if c_clean in d_clean or d_clean in c_clean:
            jaccard = max(jaccard, 0.80)

        return jaccard

    def _score_parties(
        self,
        required_parties: List[str],
        detected_parties: List[str],
        preamble_text: str,
    ) -> float:
        if not required_parties:
            return 0.5

        score_acc = 0.0
        preamble_lower = preamble_text.lower()

        for req in required_parties:
            req_clean = self._clean_legal_text(req)
            found = False
            for det in detected_parties:
                if req_clean in self._clean_legal_text(det):
                    score_acc += 1.0
                    found = True
                    break
            if not found and req_clean in preamble_lower:
                score_acc += 0.85
                found = True

        return score_acc / len(required_parties)

    def _score_content_overlap(self, query_text: str, doc_text: str) -> float:
        q_tokens = [w for w in self._tokenize(query_text) if w not in self.LEGAL_STOPWORDS]
        d_tokens = [w for w in self._tokenize(doc_text[:8000]) if w not in self.LEGAL_STOPWORDS]

        if not q_tokens or not d_tokens:
            return 0.0

        q_counts = Counter(q_tokens)
        d_counts = Counter(d_tokens)

        intersection = set(q_counts.keys()) & set(d_counts.keys())
        dot_product = sum(q_counts[k] * d_counts[k] for k in intersection)

        q_mag = math.sqrt(sum(v ** 2 for v in q_counts.values()))
        d_mag = math.sqrt(sum(v ** 2 for v in d_counts.values()))

        if q_mag == 0 or d_mag == 0:
            return 0.0

        return dot_product / (q_mag * d_mag)

    def _score_category_affinity(self, category_str: str, doc_text: str) -> float:
        text_lower = doc_text[:5000].lower()
        cat_lower = category_str.lower()

        if "governance" in cat_lower or "resolution" in cat_lower:
            if any(k in text_lower for k in ["resolved", "unanimous", "board of directors", "stockholders", "bylaws"]):
                return 0.9
        elif "regulatory" in cat_lower or "consent" in cat_lower:
            if any(k in text_lower for k in ["hart-scott-rodino", "hsr", "antitrust", "consent of landlord", "secretary of state"]):
                return 0.9
        elif "officer" in cat_lower or "certificate" in cat_lower:
            if any(k in text_lower for k in ["certifies that", "incumbency", "closing certificate", "opinion of counsel"]):
                return 0.9
        elif "financial" in cat_lower or "flow" in cat_lower:
            if any(k in text_lower for k in ["wire instructions", "funds flow", "payoff", "debt settlement", "aba:"]):
                return 0.9

        return 0.4

    def _clean_legal_text(self, text: str) -> str:
        s = text.lower()
        s = re.sub(r"[\.,'\"\(\)\[\]\{\}\-_/]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"\b[a-z]{3,}\b", text.lower())
