import json
from pathlib import Path
from docx import Document


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

            # Detect clause headings
            for rule in self.playbook["rules"]:

                if rule["clause"].lower() in text.lower():
                    current_clause = rule
                    break

            # Check the paragraph belonging to the current clause
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

            paragraph.text = proposal["after"]

        document.save(output_path)