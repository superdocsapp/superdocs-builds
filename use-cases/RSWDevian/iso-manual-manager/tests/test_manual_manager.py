import copy
import tempfile
import unittest
import json
import threading
from urllib.request import Request, urlopen
from io import BytesIO
from zipfile import ZipFile

from iso_manual import Manual, ManualManager, ManualStore, ExportBlocked, parse_mermaid, export_bytes
from iso_manual.mcp import handle_mcp
from iso_manual.api import create_server


MERMAID = '''flowchart TD
step_1["step_1 | Receive work order"]
step_2["step_2 | Inspect incoming material"]
step_4["step_4 | Release approved batch"]
step_1 --> step_2
step_2 --> step_4'''


def fixture() -> Manual:
    return Manual("manual-001", "Northwind Quality Manual", "Northwind Components", 1, "review-ready", "2026-08-09", [{
        "section_id": "process-control", "clause_ref": "8.5", "title": "Process Control",
        "body_blocks": [{"type": "step", "step_id": "step_1", "text": "Receive work order."}, {"type": "step", "step_id": "step_2", "text": "Inspect incoming material."}, {"type": "step", "step_id": "step_4", "text": "Release approved batch."}], "diagram_ref": "diagram-control", "source_refs": ["fixture.process"]
    }], [parse_mermaid("diagram-control", MERMAID)])


def update_plan():
    return {"section_id": "process-control", "diagram_id": "diagram-control", "changed_sections": ["process-control"], "changed_diagrams": ["diagram-control"], "reason": "Add verification before release", "body_blocks": [{"type": "step", "step_id": "step_1", "text": "Receive work order."}, {"type": "step", "step_id": "step_2", "text": "Inspect incoming material."}, {"type": "step", "step_id": "step_3", "text": "Verify release checks."}, {"type": "step", "step_id": "step_4", "text": "Release approved batch."}], "diagram_source": '''flowchart TD
step_1["step_1 | Receive work order"]
step_2["step_2 | Inspect incoming material"]
step_3["step_3 | Verify release checks"]
step_4["step_4 | Release approved batch"]
step_1 --> step_2
step_2 --> step_3
step_3 --> step_4'''.replace("\n+", "\n")}


class ManualManagerTests(unittest.TestCase):
    def test_paired_update_stays_consistent_and_creates_revision(self):
        manager = ManualManager(ManualStore())
        manager.create(fixture())
        proposal = manager.propose("manual-001", update_plan())
        self.assertEqual(proposal["state"], "awaiting_review")
        self.assertEqual({block["step_id"] for block in proposal["proposed"]["sections"][0]["body_blocks"]}, {"step_1", "step_2", "step_3", "step_4"})
        decision = manager.decide(proposal["proposal_id"], "approved", "quality-manager")
        self.assertEqual(decision["revision"], 2)
        exported = manager.export("manual-001", proposal["proposal_id"], "html")
        self.assertIn("not ISO certified", exported["disclaimer"])

    def test_prior_revision_is_recoverable_after_approval(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            store = ManualStore(database.name)
            manager = ManualManager(store)
            original = fixture()
            original_hash = original.content_hash()
            manager.create(original)
            proposal = manager.propose("manual-001", update_plan())
            manager.decide(proposal["proposal_id"], "approved", "quality-manager")
            recovered = store.get_revision("manual-001", 1)
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered[1], original_hash)

    def test_rejected_proposal_does_not_change_manual(self):
        manager = ManualManager(ManualStore())
        original = fixture()
        manager.create(original)
        proposal = manager.propose("manual-001", update_plan())
        manager.decide(proposal["proposal_id"], "rejected", "quality-manager")
        self.assertEqual(manager.store.get_manual("manual-001").content_hash(), original.content_hash())
        with self.assertRaises(ExportBlocked):
            manager.export("manual-001", proposal["proposal_id"])

    def test_scope_violation_is_blocked(self):
        manager = ManualManager(ManualStore())
        manager.create(fixture())
        plan = update_plan()
        plan["changed_sections"] = ["process-control", "other-section"]
        proposal = manager.propose("manual-001", plan)
        self.assertEqual(proposal["state"], "blocked")
        self.assertIn("scope", proposal["refusal"])

    def test_prose_diagram_mismatch_is_blocked(self):
        manager = ManualManager(ManualStore())
        manager.create(fixture())
        plan = update_plan()
        plan["body_blocks"] = plan["body_blocks"][:-1]
        proposal = manager.propose("manual-001", plan)
        self.assertEqual(proposal["state"], "blocked")
        self.assertIn("step IDs differ", proposal["refusal"])

    def test_unknown_edge_is_rejected_by_parser(self):
        with self.assertRaises(ValueError):
            parse_mermaid("diagram-control", MERMAID + "\nstep_4 --> missing")

    def test_approval_of_stale_proposal_is_refused(self):
        manager = ManualManager(ManualStore())
        manager.create(fixture())
        first = manager.propose("manual-001", update_plan())
        second = manager.propose("manual-001", update_plan())
        manager.decide(first["proposal_id"], "approved", "quality-manager")
        with self.assertRaises(ExportBlocked) as error:
            manager.decide(second["proposal_id"], "approved", "quality-manager")
        self.assertEqual(error.exception.code, "STALE_PROPOSAL")

    def test_manual_docx_and_pdf_exports_are_real_artifacts(self):
        manual = fixture()
        html_type, html_bytes = export_bytes(manual, "html")
        docx_type, docx_bytes = export_bytes(manual, "docx")
        pdf_type, pdf_bytes = export_bytes(manual, "pdf")
        self.assertEqual(html_type, "text/html")
        self.assertIn(b"not ISO certified", html_bytes)
        self.assertEqual(docx_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with ZipFile(BytesIO(docx_bytes)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
        self.assertEqual(pdf_type, "application/pdf")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))

    def test_mcp_and_manager_agree_on_manual_state(self):
        manager = ManualManager(ManualStore())
        created = manager.create(fixture())
        response = handle_mcp(manager, {"jsonrpc": "2.0", "id": 1, "method": "manual_get", "params": {"manual_id": "manual-001"}})
        self.assertEqual(response["result"]["content_hash"], created["content_hash"])

    def test_rest_manual_start_and_get(self):
        server = create_server(port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = fixture().to_dict()
            request = Request(f"{base}/v1/builds/manual", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            created = json.loads(urlopen(request).read())
            fetched = json.loads(urlopen(f"{base}/v1/manuals/manual-001").read())
            self.assertEqual(fetched["content_hash"], created["content_hash"])
        finally:
            server.shutdown(); server.server_close()


if __name__ == "__main__":
    unittest.main()
