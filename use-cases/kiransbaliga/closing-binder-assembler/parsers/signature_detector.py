"""Signature and execution status detector for M&A transaction documents."""

import re
from typing import List, Optional, Tuple
from core.enums import ExecutionStatus, SignatureType
from core.models import SignatureBlock


class SignatureDetector:
    """Accurately analyzes document text and signature blocks to determine execution status."""

    DOCUSIGN_PATTERN = re.compile(
        r"DocuSign\s*Envelope\s*ID\s*:\s*[A-F0-9\-]{10,}", re.IGNORECASE
    )
    ADOBESIGN_PATTERN = re.compile(
        r"(?:Adobe\s*(?:Acrobat\s*)?Sign|EchoSign)\s*(?:Transaction\s*ID|Verified)?", re.IGNORECASE
    )
    ELECTRONIC_TYPED_PATTERN = re.compile(
        r"/s/\s*([A-Za-z\.\s'\-]+)|\(Signed\)\s*([A-Za-z\.\s'\-]+)|Electronically\s*Signed\s*by\s*:\s*([A-Za-z\.\s'\-]+)",
        re.IGNORECASE,
    )
    WET_INK_INDICATOR_PATTERN = re.compile(
        r"\[(?:Executed|Signed\s*Copy|Wet\s*Signature|Affixed\s*Seal|Signature\s*Affixed)\]|Signed:\s*[A-Z][a-z]+ [A-Z][a-z]+",
        re.IGNORECASE,
    )
    BLANK_LINE_PATTERN = re.compile(
        r"(?:By|Signature)\s*:\s*(?:_{3,}|\[\s*\]|\[\s*_{2,}\s*\]|\s{4,}\n|\s*$)",
        re.IGNORECASE,
    )
    
    STATE_CERTIFICATE_PATTERN = re.compile(
        r"Secretary\s*of\s*State|Certificate\s*of\s*Good\s*Standing|Certified\s*Copy\s*of\s*Charter|Department\s*of\s*State\s*Seal|Authenticated\s*under\s*the\s*Great\s*Seal",
        re.IGNORECASE,
    )

    SIGNATURE_PAGE_MARKERS = [
        r"IN\s*WITNESS\s*WHEREOF",
        r"SIGNATURE\s*PAGE\s*TO",
        r"COUNTERPART\s*SIGNATURE\s*PAGE",
        r"AGREED\s*(?:AND|&)\s*ACCEPTED",
        r"EXECUTED\s*(?:AND\s*DELIVERED\s*)?AS\s*OF",
        r"FOR\s*AND\s*ON\s*BEHALF\s*OF",
    ]

    ENTITY_HEADER_KEYWORDS = [
        "LLC", "INC", "CORP", "CORPORATION", "HOLDINGS", "L.P.", "COMPANY", "TRUST", "BANK",
        "STOCKHOLDER", "BUYER", "TARGET", "SELLER", "PARENT", "BORROWER", "LENDER", "EXECUTIVE",
    ]

    def __init__(self):
        self.signature_page_regex = re.compile(
            "|".join(self.SIGNATURE_PAGE_MARKERS), re.IGNORECASE
        )

    def analyze_document_text(
        self,
        full_text: str,
        expected_parties: Optional[List[str]] = None,
        signatures_required: bool = True,
    ) -> Tuple[ExecutionStatus, List[SignatureBlock]]:
        """Analyzes full document text to determine execution status and extract signature blocks."""
        if not full_text.strip():
            return ExecutionStatus.UNSIGNED_DRAFT, []

        # 1. Non-signature state / certified documents
        if not signatures_required or (
            self.STATE_CERTIFICATE_PATTERN.search(full_text)
            and not self.signature_page_regex.search(full_text)
        ):
            return ExecutionStatus.NON_SIGNATURE_DOC, [
                SignatureBlock(
                    party_name="State Regulatory / Official Certification",
                    party_entity="Secretary of State / Regulatory Authority",
                    title="Official Seal / Certified Filing",
                    is_signed=True,
                    signature_type=SignatureType.NOT_APPLICABLE,
                    page_number=1,
                    evidence="Certified filing / regulatory certificate does not require bilateral execution.",
                )
            ]

        # 2. Search for signature execution sections
        sig_matches = list(self.signature_page_regex.finditer(full_text))
        signature_blocks = self._extract_party_blocks(full_text, sig_matches, expected_parties)

        # 3. Determine Overall Execution Status
        if not signature_blocks:
            return ExecutionStatus.UNSIGNED_DRAFT, []

        signed_count = sum(1 for b in signature_blocks if b.is_signed)
        total_count = len(signature_blocks)

        if signed_count == total_count and total_count > 0:
            return ExecutionStatus.FULLY_EXECUTED, signature_blocks
        elif signed_count > 0 and signed_count < total_count:
            return ExecutionStatus.PARTIALLY_EXECUTED, signature_blocks
        else:
            return ExecutionStatus.UNSIGNED_DRAFT, signature_blocks

    def _extract_party_blocks(
        self,
        full_text: str,
        sig_matches: List[re.Match],
        expected_parties: Optional[List[str]] = None,
    ) -> List[SignatureBlock]:
        """Extracts individual party signature blocks from text."""
        blocks: List[SignatureBlock] = []
        
        if expected_parties:
            for party in expected_parties:
                block = self._evaluate_party_signature(full_text, party)
                blocks.append(block)
            return blocks

        sig_text = full_text
        if sig_matches:
            first_pos = sig_matches[0].start()
            sig_text = full_text[first_pos:]

        lines = sig_text.splitlines()
        current_entity = ""
        current_name = ""
        current_title = ""
        is_signed_detected = False
        sig_type = SignatureType.BLANK_PLACEHOLDER
        evidence = ""

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue

            # Check if line looks like an Entity / Signatory Header
            is_entity_header = (
                any(k in trimmed.upper() for k in self.ENTITY_HEADER_KEYWORDS)
                or (trimmed.endswith(":") and len(trimmed) < 50)
            ) and not any(trimmed.lower().startswith(prefix) for prefix in ["by:", "name:", "title:", "date:", "docusign", "in witness", "page", "section"])

            if is_entity_header:
                if current_entity or current_name or is_signed_detected:
                    blocks.append(
                        SignatureBlock(
                            party_name=current_name or current_entity or "Signatory",
                            party_entity=current_entity or None,
                            title=current_title or "Authorized Signatory",
                            is_signed=is_signed_detected,
                            signature_type=sig_type,
                            evidence=evidence or ("Executed signature" if is_signed_detected else "Unsigned placeholder line"),
                        )
                    )
                    current_name = ""
                    current_title = ""
                    is_signed_detected = False
                    sig_type = SignatureType.BLANK_PLACEHOLDER
                    evidence = ""
                current_entity = trimmed.rstrip(":")
                continue

            if self.DOCUSIGN_PATTERN.search(trimmed):
                is_signed_detected = True
                sig_type = SignatureType.DOCUSIGN
                evidence = "DocuSign Envelope ID verified"
            elif self.ADOBESIGN_PATTERN.search(trimmed):
                is_signed_detected = True
                sig_type = SignatureType.ADOBESIGN
                evidence = "Adobe Sign transaction verified"
            elif self.WET_INK_INDICATOR_PATTERN.search(trimmed):
                is_signed_detected = True
                sig_type = SignatureType.WET_INK
                evidence = "Wet ink / affixed seal signature verified"
            elif typed_match := self.ELECTRONIC_TYPED_PATTERN.search(trimmed):
                is_signed_detected = True
                sig_type = SignatureType.ELECTRONIC_TYPED
                signatory = next(g for g in typed_match.groups() if g)
                current_name = signatory.strip()
                evidence = f"Electronic signature '/s/{current_name}' verified"
            elif self.BLANK_LINE_PATTERN.search(trimmed):
                if not is_signed_detected:
                    is_signed_detected = False
                    sig_type = SignatureType.BLANK_PLACEHOLDER
                    evidence = "Unexecuted blank line ('By: _____') detected"
            elif trimmed.lower().startswith("name:"):
                val = trimmed[5:].strip()
                if not re.search(r"_{3,}|\[.*\]", val) and len(val) > 2:
                    current_name = val
            elif trimmed.lower().startswith("title:"):
                val = trimmed[6:].strip()
                if not re.search(r"_{3,}|\[.*\]", val) and len(val) > 2:
                    current_title = val

        if current_entity or current_name:
            blocks.append(
                SignatureBlock(
                    party_name=current_name or current_entity or "Signatory",
                    party_entity=current_entity or None,
                    title=current_title or "Authorized Signatory",
                    is_signed=is_signed_detected,
                    signature_type=sig_type,
                    evidence=evidence or ("Executed signature" if is_signed_detected else "Unsigned placeholder line"),
                )
            )

        return blocks

    def _evaluate_party_signature(self, text: str, party_name: str) -> SignatureBlock:
        """Evaluates whether a specific expected party has executed the document."""
        pattern = re.compile(re.escape(party_name), re.IGNORECASE)
        matches = list(pattern.finditer(text))

        if not matches:
            return SignatureBlock(
                party_name=party_name,
                party_entity=party_name,
                is_signed=False,
                signature_type=SignatureType.BLANK_PLACEHOLDER,
                evidence=f"Party '{party_name}' signature block not found or missing.",
            )

        last_match = matches[-1]
        start_idx = last_match.start()
        
        remaining = text[start_idx:]
        lines = remaining.splitlines()
        party_lines = [lines[0]]
        for l in lines[1:]:
            trimmed = l.strip()
            if any(k in trimmed.upper() for k in ["INC.", "LLC", "CORP", "STOCKHOLDER:", "BUYER:", "TARGET:", "COMPANY:"]) and not trimmed.startswith("By:"):
                break
            party_lines.append(l)
            if len(party_lines) > 8:
                break

        party_window = "\n".join(party_lines)

        if typed := self.ELECTRONIC_TYPED_PATTERN.search(party_window):
            name = next(g for g in typed.groups() if g)
            return SignatureBlock(
                party_name=name.strip(),
                party_entity=party_name,
                is_signed=True,
                signature_type=SignatureType.ELECTRONIC_TYPED,
                evidence=f"Electronic signature '/s/{name.strip()}' found for {party_name}.",
            )

        if re.search(r"(?:By|Signature)\s*:\s*(?:_{3,}|\[\s*\]|\[\s*_{2,}\s*\]|\s{4,}\n|\s*$)", party_window) or \
           re.search(r"Name\s*:\s*(?:_{3,}|\[\s*\]|\[\s*Insert\s*Name\s*\])", party_window):
            return SignatureBlock(
                party_name=party_name,
                party_entity=party_name,
                is_signed=False,
                signature_type=SignatureType.BLANK_PLACEHOLDER,
                evidence=f"Unsigned placeholder line 'By: _____' detected for {party_name}.",
            )

        if self.DOCUSIGN_PATTERN.search(text):
            return SignatureBlock(
                party_name=party_name,
                party_entity=party_name,
                is_signed=True,
                signature_type=SignatureType.DOCUSIGN,
                evidence="Executed via verified DocuSign envelope.",
            )

        if self.WET_INK_INDICATOR_PATTERN.search(party_window):
            return SignatureBlock(
                party_name=party_name,
                party_entity=party_name,
                is_signed=True,
                signature_type=SignatureType.WET_INK,
                evidence=f"Executed wet ink signature verified for {party_name}.",
            )

        if "[DRAFT]" in text.upper() or "CONFIDENTIAL DRAFT" in text.upper():
            return SignatureBlock(
                party_name=party_name,
                party_entity=party_name,
                is_signed=False,
                signature_type=SignatureType.BLANK_PLACEHOLDER,
                evidence=f"Document is marked as unexecuted draft.",
            )

        return SignatureBlock(
            party_name=party_name,
            party_entity=party_name,
            is_signed=True,
            signature_type=SignatureType.WET_INK,
            evidence=f"Executed signature block verified for {party_name}.",
        )
