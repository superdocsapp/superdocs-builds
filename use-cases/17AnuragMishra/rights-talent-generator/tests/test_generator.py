from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rights_talent_generator.generator import (
    draft_offline,
    draft_with_superdocs,
    html_to_markdown,
    load_terms,
    markdown_to_html,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeSuperDocsClient:
    def __init__(self, final_html: str) -> None:
        self.final_html = final_html
        self.calls: list[tuple[str, Any]] = []
        self.wait_count = 0

    def upload_document(self, path: str | Path, **kwargs: Any) -> Any:
        self.calls.append(("upload", {"path": Path(path).name, **kwargs}))
        return SimpleNamespace(filename=Path(path).name)

    def chat_async(self, **kwargs: Any) -> Any:
        self.calls.append(("chat", kwargs))
        return SimpleNamespace(job_id="j1")

    def wait(self, job_id: str, **kwargs: Any) -> Any:
        self.calls.append(("wait", {"job_id": job_id, **kwargs}))
        self.wait_count += 1
        if self.wait_count == 1:
            return SimpleNamespace(
                job_id="j1",
                status="awaiting_approval",
                metadata={
                    "awaiting_kind": "change_review",
                    "pending_changes": [
                        {
                            "change_id": "c1",
                            "operation": "replace",
                            "ai_explanation": "Fill deal terms",
                        }
                    ],
                },
                error=None,
                result=None,
            )
        return SimpleNamespace(
            job_id="j1",
            status="completed",
            metadata={},
            error=None,
            result=SimpleNamespace(
                document_changes=SimpleNamespace(updated_html=self.final_html)
            ),
        )

    def approve_change(self, **kwargs: Any) -> Any:
        self.calls.append(("approve", kwargs))
        return {"ok": True}

    def get_session_history(self, session_id: str, **kwargs: Any) -> Any:
        self.calls.append(("history", {"session_id": session_id, **kwargs}))
        return SimpleNamespace(document_html=self.final_html)

    def export_document(self, **kwargs: Any) -> Any:
        self.calls.append(("export", kwargs))
        return SimpleNamespace(content=b"PK\x03\x04DOCX")


class GeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.terms = load_terms(ROOT / "fixtures" / "maya-chen-deal.json")
        self.template_path = ROOT / "fixtures" / "template.md"
        self.template = self.template_path.read_text(encoding="utf-8")

    def test_offline_draft_reflects_required_deal_terms(self) -> None:
        result = draft_offline(self.terms, self.template)
        self.assertTrue(result.is_complete)
        self.assertIn("24 months from first campaign publication", result.markdown)
        self.assertIn("$110,000 fixed fee plus approved travel", result.markdown)
        self.assertIn("connected TV", result.markdown)

    def test_live_contract_uses_upload_chat_item_gate_and_export(self) -> None:
        expected = draft_offline(self.terms, self.template)
        client = FakeSuperDocsClient(markdown_to_html(expected.markdown))
        reviewed: list[str] = []
        result = draft_with_superdocs(
            self.terms,
            self.template_path,
            approve=lambda change: reviewed.append(str(change["change_id"])) or True,
            client=client,
        )

        self.assertTrue(result.is_complete)
        self.assertEqual(b"PK\x03\x04DOCX", result.exported_docx)
        self.assertEqual(["c1"], reviewed)
        self.assertEqual(1, result.reviewed_changes)
        operations = [name for name, _ in client.calls]
        self.assertLess(operations.index("upload"), operations.index("chat"))
        self.assertLess(operations.index("chat"), operations.index("approve"))
        self.assertLess(operations.index("approve"), operations.index("export"))
        approval = next(payload for name, payload in client.calls if name == "approve")
        self.assertTrue(approval["changes"][0].approved)
        self.assertEqual("ask_every_time", next(p for n, p in client.calls if n == "chat")["approval_mode"])

    def test_html_conversion_discards_attributes_without_leaking_markup(self) -> None:
        converted = html_to_markdown(
            '<h1 data-chunk-id="a">Agreement &amp; Terms</h1><p data-chunk-id="b">No <b>markup</b> leak.</p>'
        )
        self.assertEqual("# Agreement & Terms\n\nNo markup leak.\n", converted)
        self.assertNotIn("data-chunk-id", converted)

    def test_template_path_is_really_opened_by_upload_contract(self) -> None:
        expected = draft_offline(self.terms, self.template)
        client = FakeSuperDocsClient(markdown_to_html(expected.markdown))
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "custom-template.md"
            template.write_text(self.template, encoding="utf-8")
            draft_with_superdocs(self.terms, template, approve=lambda _: True, client=client)
        upload = next(payload for name, payload in client.calls if name == "upload")
        self.assertEqual("custom-template.md", upload["path"])


if __name__ == "__main__":
    unittest.main()
