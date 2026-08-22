from src.code_diff import diff_functions


def test_signature_change_is_detected():
    old = "def greet(name):\n    return f'Hello {name}'\n"
    new = "def greet(name: str, formal: bool = False) -> str:\n    return f'Hello {name}'\n"
    changes = diff_functions(old, new, file_path="greet.py")
    assert len(changes) == 1
    assert changes[0].change_type == "signature_changed"
    assert changes[0].name == "greet"
    assert "formal" in changes[0].new.signature
    assert changes[0].citation() == "greet.py:1"


def test_internal_refactor_with_unchanged_signature_produces_no_change():
    """The core guarantee: rewriting a function's BODY without touching its signature or docstring must
    produce zero proposed changes -- this is what stops DocSync from nagging about every commit."""
    old = """
def compute_total(items):
    total = 0
    for item in items:
        total += item.price
    return total
"""
    new = """
def compute_total(items):
    return sum(item.price for item in items)
"""
    changes = diff_functions(old, new, file_path="calc.py")
    assert changes == [], "an internal-only refactor must not be flagged as a doc-relevant change"


def test_added_function_is_detected():
    old = "def foo():\n    pass\n"
    new = "def foo():\n    pass\n\ndef bar(x: int) -> int:\n    return x * 2\n"
    changes = diff_functions(old, new, file_path="mod.py")
    assert len(changes) == 1
    assert changes[0].change_type == "added"
    assert changes[0].name == "bar"


def test_removed_function_is_detected():
    old = "def foo():\n    pass\n\ndef bar():\n    pass\n"
    new = "def foo():\n    pass\n"
    changes = diff_functions(old, new, file_path="mod.py")
    assert len(changes) == 1
    assert changes[0].change_type == "removed"
    assert changes[0].name == "bar"


def test_docstring_only_change_is_detected_separately_from_signature_change():
    old = 'def foo(x):\n    """Old docs."""\n    return x\n'
    new = 'def foo(x):\n    """New, better docs."""\n    return x\n'
    changes = diff_functions(old, new, file_path="mod.py")
    assert len(changes) == 1
    assert changes[0].change_type == "docstring_changed"


def test_new_file_all_functions_are_added():
    changes = diff_functions("", "def new_func():\n    pass\n", file_path="new.py")
    assert len(changes) == 1
    assert changes[0].change_type == "added"


def test_describe_reads_naturally_for_each_change_type():
    old = "def f(a):\n    pass\n"
    new = "def f(a, b):\n    pass\n"
    change = diff_functions(old, new, file_path="x.py")[0]
    text = change.describe()
    assert "signature changed" in text
    assert "f" in text
