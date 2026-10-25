import copy
import json
import tempfile
import threading
from urllib.request import Request, urlopen
import unittest
from zipfile import ZipFile
from io import BytesIO

from invoice_companion import (
    ExportBlocked,
    FakeSuperDocsTransport,
    DurableStore,
    InvoiceService,
    InvoiceRun,
    UnknownRemoteOutcome,
    canonicalize_invoice,
    create_source_snapshot,
    reconcile_invoice,
    render_invoice,
    handle_mcp,
    export_bytes,
)
from invoice_companion.server import create_server


FIXTURE = {
    "schema_version": "invoice.v1",
    "invoice_id": "INV-1007",
    "issue_date": "2026-08-08",
    "due_date": "2026-09-07",
    "seller": {"name": "Northwind Components", "tax_id": "SYN-SELLER-01"},
    "buyer": {"name": "Fabrikam Labs", "tax_id": "SYN-BUYER-01"},
    "currency": "USD",
    "line_items": [{
        "row_id": "row-1", "description": "Sensor assembly", "quantity": "4",
        "unit_price": "125.00", "line_total": "500.00", "source_pointer": "payload.line_items[0]",
    }],
    "subtotal": "500.00", "tax": "50.00", "total": "550.00", "payment_terms": "Net 30",
}


class InvoiceCompanionTests(unittest.TestCase):
    def test_rendered_table_and_extract_carry_source_values(self):
        snapshot = create_source_snapshot(FIXTURE)
        document = render_invoice(snapshot)
        self.assertEqual(document["structured_extract"], snapshot.record)
        self.assertEqual(document["table"][0]["line_total"], "500.00")
        self.assertEqual(document["fields"]["total"], "550.00")
        self.assertEqual(reconcile_invoice(snapshot, document)["status"], "passed")

    def test_deliberate_total_mutation_is_hard_failure(self):
        snapshot = create_source_snapshot(FIXTURE)
        document = render_invoice(snapshot)
        document["fields"]["total"] = "650.00"
        result = reconcile_invoice(snapshot, document)
        finding = next(item for item in result["findings"] if item["location"] == "fields.total")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(finding["severity"], "hard_failure")
        self.assertEqual(finding["expected"], "550.00")
        self.assertEqual(finding["observed"], "650.00")
        self.assertEqual(finding["source_pointer"], "payload.total")

    def test_unsupported_narrative_figure_is_reported(self):
        snapshot = create_source_snapshot(FIXTURE)
        document = render_invoice(snapshot)
        document["narrative"] = "Invoice INV-1007 totals USD 650.00 and is due 2026-09-07."
        result = reconcile_invoice(snapshot, document)
        finding = next(item for item in result["findings"] if item["code"] == "unsupported")
        self.assertEqual(finding["observed"], "650.00")

    def test_snapshot_is_immutable_and_hash_is_content_addressed(self):
        source = copy.deepcopy(FIXTURE)
        snapshot = create_source_snapshot(source)
        source["total"] = "650.00"
        self.assertEqual(snapshot.record["total"], "550.00")
        self.assertNotEqual(snapshot.source_hash, create_source_snapshot(source).source_hash)

    def test_duplicate_row_ids_are_rejected(self):
        invalid = copy.deepcopy(FIXTURE)
        invalid["line_items"].append(copy.deepcopy(invalid["line_items"][0]))
        with self.assertRaises(ValueError):
            canonicalize_invoice(invalid)

    def test_failed_reconciliation_cannot_be_exported_after_approval(self):
        snapshot = create_source_snapshot(FIXTURE)
        document = render_invoice(snapshot)
        document["fields"]["total"] = "650.00"
        transport = FakeSuperDocsTransport()
        run = InvoiceRun(snapshot, document, transport)
        run.submit("run-1")
        item_id = next(iter(run.items))
        run.decide(item_id, "approved", "reviewer@example.test", "run-1")
        with self.assertRaises(ExportBlocked) as error:
            run.export_verified("run-1")
        self.assertEqual(error.exception.code, "RECONCILIATION_GATE_BLOCKED")
        self.assertEqual(run.state, "failed")

    def test_accepted_exception_remains_failed_and_blocks_export(self):
        snapshot = create_source_snapshot(FIXTURE)
        document = render_invoice(snapshot)
        document["fields"]["total"] = "650.00"
        run = InvoiceRun(snapshot, document, FakeSuperDocsTransport())
        item_id = next(iter(run.items))
        run.decide(item_id, "accepted_exception", "reviewer@example.test", "run-2")
        self.assertEqual(run.state, "failed_with_accepted_exceptions")
        with self.assertRaises(ExportBlocked):
            run.export_verified("run-2")

    def test_unknown_remote_outcome_retries_by_key_without_duplicate_operation(self):
        transport = FakeSuperDocsTransport()
        transport.timeout_once("run-3:upload")
        with self.assertRaises(UnknownRemoteOutcome):
            transport.upload("run-3:upload", {"source_hash": "abc"})
        result = transport.upload("run-3:upload", {"source_hash": "abc"})
        self.assertEqual(result["document"]["source_hash"], "abc")
        self.assertEqual(len(transport.events), 2)
        self.assertFalse(transport.events[0].replayed)
        self.assertTrue(transport.events[1].replayed)

    def test_clean_run_exports_once_and_replay_is_idempotent(self):
        snapshot = create_source_snapshot(FIXTURE)
        transport = FakeSuperDocsTransport()
        run = InvoiceRun(snapshot, render_invoice(snapshot), transport)
        run.submit("run-4")
        first = run.export_verified("run-4")
        second = run.export_verified("run-4")
        self.assertEqual(first, second)
        exports = [event for event in transport.events if event.operation == "export"]
        self.assertEqual(len(exports), 2)
        self.assertEqual([event.replayed for event in exports], [False, True])

    def test_durable_service_survives_reconstruction_and_keeps_tenants_isolated(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            service = InvoiceService(DurableStore(database.name))
            started = service.start("tenant-a", FIXTURE)
            run_id = started["run_id"]
            restarted = InvoiceService(DurableStore(database.name))
            self.assertEqual(restarted.get("tenant-a", run_id)["source_hash"], started["source_hash"])
            with self.assertRaises(Exception):
                restarted.get("tenant-b", run_id)

    def test_mcp_and_service_return_equivalent_machine_state(self):
        service = InvoiceService(DurableStore())
        rest_state = service.start("tenant-a", FIXTURE)
        mcp_state = handle_mcp(service, {"jsonrpc": "2.0", "id": 1, "method": "invoice_get", "params": {"run_id": rest_state["run_id"]}}, "tenant-a")
        self.assertEqual(mcp_state["result"]["run_id"], rest_state["run_id"])
        self.assertEqual(mcp_state["result"]["state"], rest_state["state"])

    def test_mcp_export_refusal_is_machine_readable(self):
        service = InvoiceService(DurableStore())
        source = copy.deepcopy(FIXTURE)
        started = service.start("tenant-a", {"invoice": source})
        service.chat("tenant-a", started["run_id"], {"document": {**render_invoice(create_source_snapshot(source)), "fields": {**render_invoice(create_source_snapshot(source))["fields"], "total": "650.00"}}})
        response = handle_mcp(service, {"jsonrpc": "2.0", "id": 2, "method": "invoice_export", "params": {"run_id": started["run_id"]}}, "tenant-a")
        self.assertEqual(response["error"]["code"], "RECONCILIATION_GATE_BLOCKED")

    def test_rest_lifecycle_uses_same_durable_state(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            server = create_server(port=0, database=database.name)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(f"{base}/v1/builds/invoice", data=json.dumps(FIXTURE).encode(), headers={"Content-Type": "application/json", "X-Tenant-ID": "tenant-rest"})
                started = json.loads(urlopen(request).read())
                fetched = json.loads(urlopen(Request(f"{base}/v1/runs/{started['run_id']}", headers={"X-Tenant-ID": "tenant-rest"})).read())
                self.assertEqual(fetched["run_id"], started["run_id"])
                self.assertEqual(fetched["state"], "passed")
            finally:
                server.shutdown()
                server.server_close()

    def test_docx_pdf_and_html_exports_are_real_artifacts(self):
        document = render_invoice(create_source_snapshot(FIXTURE))
        html_type, html_bytes = export_bytes(document, "html")
        docx_type, docx_bytes = export_bytes(document, "docx")
        pdf_type, pdf_bytes = export_bytes(document, "pdf")
        self.assertEqual(html_type, "text/html")
        self.assertIn(b"Invoice INV-1007", html_bytes)
        self.assertEqual(docx_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with ZipFile(BytesIO(docx_bytes)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
            self.assertIn(b"550.00", archive.read("word/document.xml"))
        self.assertEqual(pdf_type, "application/pdf")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))


if __name__ == "__main__":
    unittest.main()
