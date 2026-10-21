"""Character-level diff token generation for screenplay formatting review"""
import difflib
from typing import List, Dict, Any


def compute_diff_tokens(original: str, formatted: str) -> List[Dict[str, Any]]:
    """
    Compute character-level diff tokens between original and formatted text.
    Returns list of {"type": "equal"|"insert"|"delete", "text": "..."}.
    """
    if not original and not formatted:
        return []

    matcher = difflib.SequenceMatcher(None, original, formatted, autojunk=False)
    tokens = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            tokens.append({"type": "equal", "text": original[i1:i2]})
        elif tag == "replace":
            tokens.append({"type": "delete", "text": original[i1:i2]})
            tokens.append({"type": "insert", "text": formatted[j1:j2]})
        elif tag == "delete":
            tokens.append({"type": "delete", "text": original[i1:i2]})
        elif tag == "insert":
            tokens.append({"type": "insert", "text": formatted[j1:j2]})
    return tokens
