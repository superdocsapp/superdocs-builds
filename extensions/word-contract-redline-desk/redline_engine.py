import json
from pathlib import Path
from datetime import datetime, timezone

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


class RedlineEngine:

    def __init__(self, playbook_path):
        self.playbook_path = Path(playbook_path)

        with open(self.playbook_path, "r", encoding="utf-8") as f:
            self.playbook = json.load(f)

    def load_document(self, document_path):
        document = Document(document_path)

        paragraphs = []

        for index, paragraph in enumerate(document.paragraphs):
            text = paragraph.text.strip()

            if text:
                paragraphs.append({
                    "index": index,
                    "text": text,
                    "style": paragraph.style.name
                })

        return paragraphs

    def review(self, document_path):
        paragraphs = self.load_document(document_path)

        proposals = []
        current_clause = None

        for paragraph in paragraphs:

            text = paragraph["text"]

            for rule in self.playbook["rules"]:

                if rule["clause"].lower() in text.lower():
                    current_clause = rule
                    break

            if current_clause:

                proposal = self._create_proposal(
                    paragraph,
                    current_clause
                )

                if proposal:
                    proposals.append(proposal)
                    current_clause = None

        return proposals

    def _create_proposal(self, paragraph, rule):

        text = paragraph["text"]

        if rule["clause"].lower() == "limitation of liability":

            if "unlimited" in text.lower():

                replacement = (
                    "The liability of each party under this Agreement "
                    "shall be limited to the total fees paid under this Agreement."
                )

                return {
                    "id": len(text),
                    "clause": rule["clause"],
                    "paragraph_index": paragraph["index"],
                    "before": text,
                    "after": replacement,
                    "reason": rule["instruction"],
                    "status": "pending"
                }

        return None

    def apply_approved_changes(
        self,
        document_path,
        proposals,
        output_path
    ):

        document = Document(document_path)

        approved = [
            proposal
            for proposal in proposals
            if proposal["status"] == "approved"
        ]

        for proposal in approved:

            paragraph = document.paragraphs[
                proposal["paragraph_index"]
            ]

            # Remove existing paragraph content,
            # but preserve paragraph properties.
            for child in list(paragraph._p):
                if child.tag != qn("w:pPr"):
                    paragraph._p.remove(child)

            # -----------------------------
            # TRACKED DELETION
            # -----------------------------

            deletion = OxmlElement("w:del")

            deletion.set(
                qn("w:id"),
                str(proposal["id"])
            )

            deletion.set(
                qn("w:author"),
                "SuperDocs"
            )

            deletion.set(
                qn("w:date"),
                datetime.now(timezone.utc).isoformat()
            )

            deleted_run = OxmlElement("w:r")

            deleted_text = OxmlElement("w:delText")
            deleted_text.set(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve"
            )

            deleted_text.text = proposal["before"]

            deleted_run.append(deleted_text)
            deletion.append(deleted_run)

            paragraph._p.append(deletion)

            # -----------------------------
            # TRACKED INSERTION
            # -----------------------------

            insertion = OxmlElement("w:ins")

            insertion.set(
                qn("w:id"),
                str(proposal["id"] + 1000)
            )

            insertion.set(
                qn("w:author"),
                "SuperDocs"
            )

            insertion.set(
                qn("w:date"),
                datetime.now(timezone.utc).isoformat()
            )

            inserted_run = OxmlElement("w:r")

            inserted_text = OxmlElement("w:t")
            inserted_text.set(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve"
            )

            inserted_text.text = proposal["after"]

            inserted_run.append(inserted_text)
            insertion.append(inserted_run)

            paragraph._p.append(insertion)

        document.save(output_path)