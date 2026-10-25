import json
import tempfile
import threading
import unittest
from io import BytesIO
from urllib.request import Request, urlopen
from zipfile import ZipFile

from patent_claims import (
    ClaimManager,
    ClaimStore,
    ClaimValidationError,
    ExportBlocked,
    Patent,
    amend_claim,
    build_claim_set,
    delete_claim,
    export_bytes,
    handle_mcp,
    patent_from_payload,
)
from patent_claims.server import create_server


def fixture() -> Patent:
    return Patent(
        patent_id="patent-001",
        title="Modular Sensor Mount",
        applicant="Northwind Components",
        revision=1,
        status="review-ready",
        claims=build_claim_set([
            {"number": 1, "text": "A sensor mount assembly comprising a base plate and a swivel joint."},
            {"number": 2, "text": "The sensor mount assembly of claim 1, wherein the swivel joint includes a locking collar."},
            {"number": 3, "text": "The sensor mount assembly of claim 2, wherein the locking collar is spring-loaded."},
        ]),
    )


def amend_claim_1_plan() -> dict:
    return {
        "action": "amend", "claim_number": 1,
        "new_text": "A sensor mount assembly comprising a base plate, a swivel joint, and a vibration damper.",
        "reason": "Add vibration damper limitation to independent claim 1.",
    }


class PatentClaimsCoreTests(unittest.TestCase):
    def test_build_claim_set_derives_dependencies_and_kind(self):
        claim_set = fixture().claims
        by_number = claim_set.by_number()
        self.assertEqual(by_number[1].kind, "independent")
        self.assertEqual(by_number[2].depends_on, (1,))
        self.assertEqual(by_number[3].depends_on, (2,))

    def test_duplicate_claim_number_is_rejected(self):
        with self.assertRaises(ClaimValidationError):
            build_claim_set([{"number": 1, "text": "A widget."}, {"number": 1, "text": "Another widget."}])

    def test_noncontiguous_claim_numbers_are_rejected(self):
        with self.assertRaises(ClaimValidationError):
            build_claim_set([{"number": 1, "text": "A widget."}, {"number": 3, "text": "The widget of claim 1."}])

    def test_dangling_reference_is_rejected(self):
        with self.assertRaises(ClaimValidationError):
            build_claim_set([{"number": 1, "text": "The widget of claim 5."}])

    def test_amend_independent_claim_flags_transitive_dependents(self):
        claim_set = fixture().claims
        _, flagged = amend_claim(claim_set, 1, "A sensor mount assembly comprising a base plate and a bearing.")
        self.assertEqual(flagged, [2, 3])

    def test_amend_does_not_silently_rewrite_dependent_text(self):
        claim_set = fixture().claims
        new_claims, _ = amend_claim(claim_set, 1, "A sensor mount assembly comprising a base plate and a bearing.")
        self.assertEqual(new_claims.by_number()[2].text, claim_set.by_number()[2].text)

    def test_delete_claim_blocked_when_dependents_exist(self):
        with self.assertRaises(ClaimValidationError):
            delete_claim(fixture().claims, 2)

    def test_delete_leaf_claim_renumbers_and_rewrites_references(self):
        new_claims = delete_claim(fixture().claims, 3)
        self.assertEqual([claim.number for claim in new_claims.claims], [1, 2])

    def test_patent_content_hash_changes_when_claims_change(self):
        patent = fixture()
        other = Patent(**{**patent.__dict__, "claims": build_claim_set([{"number": 1, "text": "A different widget."}])})
        self.assertNotEqual(patent.content_hash(), other.content_hash())

    def test_patent_from_payload_derives_dependencies_from_raw_text(self):
        patent = patent_from_payload({
            "patent_id": "patent-002", "title": "Widget", "applicant": "Acme",
            "claims": [{"number": 1, "text": "A widget."}, {"number": 2, "text": "The widget of claim 1, in blue."}],
        })
        self.assertEqual(patent.claims.by_number()[2].depends_on, (1,))


class ClaimManagerTests(unittest.TestCase):
    def test_propose_amendment_is_awaiting_review_and_reports_flagged_dependents(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", amend_claim_1_plan())
        self.assertEqual(proposal["state"], "awaiting_review")
        self.assertEqual(proposal["flagged_dependents"], [2, 3])
        self.assertEqual(len(proposal["diff"]), 1)

    def test_propose_with_unknown_claim_is_blocked_not_raised(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", {"action": "amend", "claim_number": 99, "new_text": "x"})
        self.assertEqual(proposal["state"], "blocked")
        self.assertIn("does not exist", proposal["refusal"])

    def test_propose_delete_of_depended_on_claim_is_blocked(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", {"action": "delete", "claim_number": 1})
        self.assertEqual(proposal["state"], "blocked")
        self.assertIn("depend on it", proposal["refusal"])

    def test_approving_amendment_creates_new_revision_and_records_flagged_dependents(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", amend_claim_1_plan())
        decision = manager.decide(proposal["proposal_id"], "approved", "attorney-1")
        self.assertEqual(decision["revision"], 2)
        patent = manager.store.get_patent("patent-001")
        self.assertEqual(patent.revision, 2)
        self.assertEqual(patent.revision_history[-1]["flagged_dependents"], [2, 3])
        self.assertIn("vibration damper", patent.claims.by_number()[1].text)

    def test_rejecting_amendment_leaves_patent_unchanged(self):
        manager = ClaimManager(ClaimStore())
        original = fixture()
        manager.create(original)
        proposal = manager.propose("patent-001", amend_claim_1_plan())
        decision = manager.decide(proposal["proposal_id"], "rejected", "attorney-1")
        self.assertEqual(decision["state"], "rejected")
        patent = manager.store.get_patent("patent-001")
        self.assertEqual(patent.revision, 1)
        self.assertEqual(patent.content_hash(), original.content_hash())

    def test_export_blocked_until_proposal_approved(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", amend_claim_1_plan())
        with self.assertRaises(ExportBlocked):
            manager.export("patent-001", proposal["proposal_id"], "html")

    def test_export_after_approval_carries_disclaimer_and_flagged_dependents(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", amend_claim_1_plan())
        manager.decide(proposal["proposal_id"], "approved", "attorney-1")
        exported = manager.export("patent-001", proposal["proposal_id"], "html")
        self.assertIn("not a filed or certified document", exported["disclaimer"])

    def test_approval_of_stale_proposal_is_refused(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        first = manager.propose("patent-001", amend_claim_1_plan())
        second = manager.propose("patent-001", {"action": "amend", "claim_number": 2, "new_text": "The sensor mount assembly of claim 1, wherein the swivel joint includes a bearing."})
        manager.decide(first["proposal_id"], "approved", "attorney-1")
        with self.assertRaises(ExportBlocked):
            manager.decide(second["proposal_id"], "approved", "attorney-1")

    def test_prior_revision_is_recoverable_after_approval(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            store = ClaimStore(database.name)
            manager = ClaimManager(store)
            original = fixture()
            original_hash = original.content_hash()
            manager.create(original)
            proposal = manager.propose("patent-001", amend_claim_1_plan())
            manager.decide(proposal["proposal_id"], "approved", "attorney-1")
            previous = store.get_revision("patent-001", 1)
            self.assertEqual(previous.content_hash(), original_hash)
            current = store.get_patent("patent-001")
            self.assertEqual(current.revision, 2)

    def test_docx_pdf_and_html_exports_are_real_artifacts(self):
        patent = fixture()
        html_type, html_bytes = export_bytes(patent, "html")
        docx_type, docx_bytes = export_bytes(patent, "docx")
        pdf_type, pdf_bytes = export_bytes(patent, "pdf")
        self.assertEqual(html_type, "text/html")
        self.assertIn(b"not a filed or certified document", html_bytes)
        self.assertEqual(docx_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with ZipFile(BytesIO(docx_bytes)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
        self.assertEqual(pdf_type, "application/pdf")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))

    def test_mcp_and_manager_agree_on_patent_state(self):
        manager = ClaimManager(ClaimStore())
        created = manager.create(fixture())
        response = handle_mcp(manager, {"jsonrpc": "2.0", "id": 1, "method": "patent_get", "params": {"patent_id": "patent-001"}})
        self.assertEqual(response["result"]["content_hash"], created["content_hash"])

    def test_mcp_export_refusal_is_machine_readable(self):
        manager = ClaimManager(ClaimStore())
        manager.create(fixture())
        proposal = manager.propose("patent-001", amend_claim_1_plan())
        response = handle_mcp(manager, {
            "jsonrpc": "2.0", "id": 2, "method": "patent_export",
            "params": {"patent_id": "patent-001", "proposal_id": proposal["proposal_id"]},
        })
        self.assertEqual(response["error"]["code"], "REVIEW_GATE_BLOCKED")


class ClaimRestTests(unittest.TestCase):
    def test_rest_lifecycle_uses_same_durable_state(self):
        server = create_server(port=0, database=":memory:")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"

            def post(path: str, body: dict) -> dict:
                request = Request(f"{base}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                with urlopen(request) as response:
                    return json.loads(response.read())

            created = post("/v1/builds/patent", {
                "patent_id": "patent-100", "title": "Bracket", "applicant": "Acme",
                "claims": [{"number": 1, "text": "A bracket."}, {"number": 2, "text": "The bracket of claim 1, made of steel."}],
            })
            self.assertEqual(created["revision"], 1)

            with urlopen(f"{base}/v1/patents/patent-100") as response:
                fetched = json.loads(response.read())
            self.assertEqual(fetched["patent"]["revision"], 1)

            proposal = post("/v1/patents/patent-100/chat", {"change_plan": {"action": "amend", "claim_number": 1, "new_text": "A bracket with a mounting hole."}})
            self.assertEqual(proposal["state"], "awaiting_review")
            self.assertEqual(proposal["flagged_dependents"], [2])

            decision = post(f"/v1/proposals/{proposal['proposal_id']}/decision", {"decision": "approved", "approver": "attorney-1"})
            self.assertEqual(decision["revision"], 2)

            exported = post("/v1/patents/patent-100/export", {"proposal_id": proposal["proposal_id"], "format": "json"})
            self.assertEqual(exported["patent"]["revision"], 2)
        finally:
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
