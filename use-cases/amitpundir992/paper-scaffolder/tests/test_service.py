from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from paper_scaffolder.documents import render_manuscript_html
from paper_scaffolder.models import PaperInputs, SectionStatus
from paper_scaffolder.service import ManuscriptService
from paper_scaffolder.superdocs import parse_proposed_change_content
from paper_scaffolder.template_parser import TemplateStructureError


TEMPLATE = """Target journal: Example Journal
Required sections:
Title
Abstract
Research Question
Methods
Data
Results
Discussion
Conclusion
References
"""

PLOS_ONE_RESEARCH_ARTICLE_TEMPLATE = """Target journal: PLOS ONE
Required sections:
Title Page
Abstract
Introduction
Materials and Methods
Results
Discussion
Acknowledgments
References
"""


def inputs(
    *,
    methodology: str = "We use a preregistered retrospective cohort design.",
    dataset_description: str = "The supplied dataset contains de-identified encounter records.",
    template: str = TEMPLATE,
) -> PaperInputs:
    return PaperInputs(
        research_question="Does the stated exposure relate to the stated outcome?",
        methodology=methodology,
        dataset_description=dataset_description,
        journal_template=template,
    )


class ManuscriptServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ManuscriptService()

    def test_valid_input_produces_manuscript_structure(self) -> None:
        scaffold = self.service.create_scaffold(inputs())

        self.assertEqual(len(scaffold.sections), 9)
        self.assertEqual(scaffold.sections[2].title, "Research Question")
        self.assertEqual(scaffold.sections[2].status, SectionStatus.AVAILABLE)

    def test_missing_results_never_produces_fabricated_results(self) -> None:
        result = self.service.generate_section(inputs(), "results")

        self.assertEqual(result.section.status, SectionStatus.INSUFFICIENT_INFORMATION)
        self.assertEqual(result.section.content, "")
        self.assertIn("No verified research results", result.section.reason)

    def test_missing_dataset_does_not_produce_dataset_facts(self) -> None:
        result = self.service.generate_section(
            inputs(dataset_description=""), "data"
        )

        self.assertEqual(result.section.status, SectionStatus.INSUFFICIENT_INFORMATION)
        self.assertEqual(result.section.content, "")
        self.assertEqual(
            result.section.reason, "No verified dataset information was provided."
        )

    def test_one_section_can_be_generated_independently(self) -> None:
        paper_inputs = inputs()
        result = self.service.generate_section(paper_inputs, "methods")
        scaffold = self.service.create_scaffold(paper_inputs)
        scaffold_methods = next(
            section for section in scaffold.sections if section.section_id == "methods"
        )

        self.assertEqual(result.section.status, SectionStatus.GENERATED)
        self.assertEqual(result.section.content, paper_inputs.methodology)
        self.assertEqual(scaffold_methods.content, paper_inputs.methodology)

    def test_supplied_methods_and_data_appear_in_scaffold_document(self) -> None:
        paper_inputs = inputs()
        scaffold = self.service.create_scaffold(paper_inputs)
        sections = {section.section_id: section for section in scaffold.sections}

        self.assertEqual(sections["methods"].content, paper_inputs.methodology)
        self.assertEqual(sections["methods"].available_sources, ("methodology",))
        self.assertEqual(sections["data"].content, paper_inputs.dataset_description)
        self.assertEqual(
            sections["results"].status,
            SectionStatus.INSUFFICIENT_INFORMATION,
        )
        self.assertEqual(sections["results"].content, "")

        document_html = render_manuscript_html(scaffold)
        self.assertIn(paper_inputs.methodology, document_html)
        self.assertIn(paper_inputs.dataset_description, document_html)
        self.assertIn("No verified research results were provided", document_html)

    def test_unsupported_section_is_explicitly_insufficient(self) -> None:
        custom = inputs(
            template="Required sections: Introduction, Methods, Results, References"
        )
        result = self.service.generate_section(custom, "introduction")

        self.assertEqual(result.section.status, SectionStatus.INSUFFICIENT_INFORMATION)
        self.assertEqual(result.section.content, "")
        self.assertIn("background sources", result.section.reason)

    def test_supplied_journal_order_is_respected(self) -> None:
        custom = inputs(
            template="Required sections: Methods; Research Question; Data; Results"
        )
        scaffold = self.service.create_scaffold(custom)

        self.assertEqual(
            [section.title for section in scaffold.sections],
            ["Methods", "Research Question", "Data", "Results"],
        )

    def test_plos_one_research_article_structure_is_respected(self) -> None:
        paper_inputs = inputs(template=PLOS_ONE_RESEARCH_ARTICLE_TEMPLATE)
        scaffold = self.service.create_scaffold(paper_inputs)
        sections = {section.title: section for section in scaffold.sections}

        self.assertEqual(
            [section.title for section in scaffold.sections],
            [
                "Title Page",
                "Abstract",
                "Introduction",
                "Materials and Methods",
                "Results",
                "Discussion",
                "Acknowledgments",
                "References",
            ],
        )
        self.assertEqual(
            sections["Materials and Methods"].content,
            f"{paper_inputs.methodology}\n\n{paper_inputs.dataset_description}",
        )
        self.assertEqual(
            sections["Materials and Methods"].available_sources,
            ("methodology", "dataset_description"),
        )
        self.assertEqual(
            sections["Results"].status,
            SectionStatus.INSUFFICIENT_INFORMATION,
        )
        self.assertEqual(sections["Results"].content, "")

        generated = self.service.generate_section(
            paper_inputs, "materials-and-methods"
        )
        self.assertEqual(generated.section.status, SectionStatus.GENERATED)
        self.assertEqual(
            generated.section.content,
            f"{paper_inputs.methodology}\n\n{paper_inputs.dataset_description}",
        )

    def test_external_writer_can_be_mocked(self) -> None:
        writer = Mock()
        writer.generate.return_value = inputs().methodology
        service = ManuscriptService(writer=writer)

        result = service.generate_section(inputs(), "methods")

        self.assertEqual(result.section.status, SectionStatus.GENERATED)
        writer.generate.assert_called_once()

    def test_ungrounded_writer_output_is_rejected(self) -> None:
        writer = Mock()
        writer.generate.return_value = "The treatment caused a statistically significant improvement."
        service = ManuscriptService(writer=writer)

        result = service.generate_section(inputs(), "methods")

        self.assertEqual(result.section.status, SectionStatus.INSUFFICIENT_INFORMATION)
        self.assertEqual(result.section.content, "")
        self.assertIn("rejected", result.section.reason)

    def test_writer_is_not_called_for_unsupported_section(self) -> None:
        writer = Mock()
        service = ManuscriptService(writer=writer)

        service.generate_section(inputs(), "results")

        writer.generate.assert_not_called()

    def test_journal_name_alone_is_not_treated_as_a_structure(self) -> None:
        with self.assertRaises(TemplateStructureError):
            self.service.create_scaffold(inputs(template="Example Journal"))

    def test_nested_json_proposed_change_content_is_parsed(self) -> None:
        encoded = json.dumps(json.dumps({"change_id": "change-1"}))

        self.assertEqual(
            parse_proposed_change_content(encoded), {"change_id": "change-1"}
        )


if __name__ == "__main__":
    unittest.main()
