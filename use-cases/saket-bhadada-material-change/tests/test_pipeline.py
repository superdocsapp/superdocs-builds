import json
import os
import unittest
from pathlib import Path

from main_mcp import deep_parse, OperationBudget, _resolve_tool_name

class TestMaterialChangePipeline(unittest.TestCase):

    def test_deep_parse_single_stringified_json(self):
        sample = json.dumps({"status": "complete", "result": {"party_favored": "Client"}})
        parsed = deep_parse(sample)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["status"], "complete")
        self.assertEqual(parsed["result"]["party_favored"], "Client")

    def test_deep_parse_nested_double_encoded_json(self):
        inner = json.dumps({"material_changes": ["liability_3x", "net_60_terms"], "rationale": "Shifted risk"})
        outer = json.dumps({"job_id": "123", "status": "completed", "findings": inner})
        parsed = deep_parse(outer)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["status"], "completed")
        self.assertIsInstance(parsed["findings"], dict)
        self.assertEqual(parsed["findings"]["material_changes"][0], "liability_3x")

    def test_deep_parse_mixed_structures_and_primitives(self):
        data = {
            "title": "Contract Brief",
            "nested_list": [json.dumps({"sub_clause": "indemnity"}), "plain_string", 42],
            "plain_number": 100,
        }
        parsed = deep_parse(data)
        self.assertIsInstance(parsed["nested_list"][0], dict)
        self.assertEqual(parsed["nested_list"][0]["sub_clause"], "indemnity")
        self.assertEqual(parsed["nested_list"][1], "plain_string")
        self.assertEqual(parsed["nested_list"][2], 42)

    def test_operation_budget_guard(self):
        budget = OperationBudget(max_calls=3, enabled=True)
        budget.spend("upload:v1")
        budget.spend("upload:v2")
        budget.spend("chat:instruction")
        self.assertEqual(budget.count, 3)
        with self.assertRaises(RuntimeError):
            budget.spend("approve:changes")

    def test_sample_contracts_exist_and_non_empty(self):
        base_dir = Path(__file__).resolve().parent.parent / "sample_data"
        v1 = base_dir / "contract_v1.txt"
        v2 = base_dir / "contract_v2.txt"
        self.assertTrue(v1.exists(), "contract_v1.txt is missing")
        self.assertTrue(v2.exists(), "contract_v2.txt is missing")
        self.assertGreater(len(v1.read_text(encoding="utf-8")), 200)
        self.assertGreater(len(v2.read_text(encoding="utf-8")), 200)

    def test_resolve_tool_name_fallback(self):
        discovered = {"upload_document", "chat_async", "approve_change", "export_document"}
        matched_upload = _resolve_tool_name(discovered, ["upload", "upload_document"])
        self.assertEqual(matched_upload, "upload_document")

        matched_chat = _resolve_tool_name(discovered, ["chat", "chat_async"])
        self.assertEqual(matched_chat, "chat_async")

if __name__ == "__main__":
    unittest.main()
