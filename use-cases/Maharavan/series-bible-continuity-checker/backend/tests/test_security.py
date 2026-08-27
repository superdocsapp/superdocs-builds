import pytest
from series_bible.application.llm import SYSTEM_INSTRUCTION

def test_prompt_marks_manuscript_as_untrusted_data():
    assert "untrusted data" in SYSTEM_INSTRUCTION
    assert "never instructions" in SYSTEM_INSTRUCTION

def test_path_traversal_is_not_a_safe_basename():
    from pathlib import PurePath
    filename="../../secrets.docx"
    assert PurePath(filename).name != filename
