from src.code_diff import diff_functions
from src.doc_index import parse_markdown_chunks
from src.sync_engine import build_proposals, apply_approved_updates
from src.fake_client import FakeSuperDocsClient


README = """
# My Library

## Usage

Call `compute_total(items)` to get the sum of all item prices in a cart.

## API Reference

### greet

The `greet` function returns a friendly greeting string for the given name.
"""


def test_documented_signature_change_produces_a_scoped_update_proposal():
    old = "def compute_total(items):\n    pass\n"
    new = "def compute_total(items, tax_rate: float = 0.0):\n    pass\n"
    changes = diff_functions(old, new, file_path="calc.py")
    chunks = parse_markdown_chunks(README)

    proposals = build_proposals(changes, chunks)
    assert len(proposals) == 1
    assert proposals[0].kind == "update_doc_section"
    assert proposals[0].citation == "calc.py:1"
    assert len(proposals[0].target_chunks) == 1
    assert "compute_total" in proposals[0].target_chunks[0].text
    assert "ONLY this section" in proposals[0].instruction


def test_undocumented_function_change_is_flagged_not_silently_dropped():
    old = "def mystery_func(a):\n    pass\n"
    new = "def mystery_func(a, b):\n    pass\n"
    changes = diff_functions(old, new, file_path="internal.py")
    chunks = parse_markdown_chunks(README)  # doesn't mention mystery_func at all

    proposals = build_proposals(changes, chunks)
    assert len(proposals) == 1
    assert proposals[0].kind == "flag_undocumented"
    assert proposals[0].instruction is None
    assert "UNDOCUMENTED" in proposals[0].summary()


def test_internal_refactor_produces_zero_proposals():
    old = "def compute_total(items):\n    total = 0\n    for i in items:\n        total += i\n    return total\n"
    new = "def compute_total(items):\n    return sum(items)\n"
    changes = diff_functions(old, new, file_path="calc.py")
    chunks = parse_markdown_chunks(README)

    proposals = build_proposals(changes, chunks)
    assert proposals == [], "an unchanged signature must produce zero proposals, even with a doc match available"


def test_removed_documented_function_proposes_removal():
    old = "def greet(name):\n    pass\n"
    new = ""
    changes = diff_functions(old, new, file_path="greet.py")
    chunks = parse_markdown_chunks(README)

    proposals = build_proposals(changes, chunks)
    assert len(proposals) == 1
    assert proposals[0].kind == "propose_removal"
    assert "removed" in proposals[0].instruction.lower()


def test_removed_undocumented_function_proposes_nothing():
    old = "def totally_internal_helper(a):\n    pass\n"
    new = ""
    changes = diff_functions(old, new, file_path="internal.py")
    chunks = parse_markdown_chunks(README)  # never mentions this function

    proposals = build_proposals(changes, chunks)
    assert proposals == [], "removing a never-documented function needs no doc action at all"


def test_apply_approved_updates_only_calls_chat_for_non_flag_proposals():
    old = "def compute_total(items):\n    pass\n"
    new = "def compute_total(items, tax_rate: float = 0.0):\n    pass\n"
    changes = diff_functions(old, new, file_path="calc.py")
    also_undocumented_old = "def mystery(a):\n    pass\n"
    also_undocumented_new = "def mystery(a, b):\n    pass\n"
    changes += diff_functions(also_undocumented_old, also_undocumented_new, file_path="internal.py")

    chunks = parse_markdown_chunks(README)
    proposals = build_proposals(changes, chunks)
    assert len(proposals) == 2  # one scoped update, one flagged-undocumented

    client = FakeSuperDocsClient()
    client.script_edit("ONLY this section", lambda html: html.replace(
        "compute_total(items)", "compute_total(items, tax_rate=0.0)"
    ))
    client.load_html(session_id="doc-1", html=README)

    results = apply_approved_updates(client, "doc-1", README, proposals)

    # Only the scoped update should have triggered a chat call -- the flagged-undocumented proposal has no
    # instruction and must not reach the API at all.
    assert len(client.chat_log) == 1
    assert len(results) == 1
    assert "calc.py:1" in results
