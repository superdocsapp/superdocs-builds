"""superdocs_kit - the thin layer both builds in this folder sit on.

Not a wrapper for its own sake. It exists because four things had to be
true for either build to be honest:

1. an operation is never spent without a durable ledger line (budget.py)
2. a key never reaches a log, a fixture or a commit (secrets.py)
3. the tests run with no key and no network (transport.py: record/replay)
4. "only the intended section changed" is proved from the bytes, not
   taken from the API's own summary (docdiff.py)
"""

from .budget import Charge, OpsBudget
from .changes import Change, changes_from, deep_parse, updated_html_from
from .client import ChatResult, SuperDocs
from .docdiff import (
    SectionDiff,
    SurgeryVerdict,
    chunk_map,
    diff_chunks,
    sha,
    text_diff,
    verify_surgical,
    visible_text,
)
from .errors import (
    ApiError,
    AuthError,
    BudgetExceeded,
    QuotaExhausted,
    ReplayMiss,
    SuperDocsError,
    TransportError,
)
from .transport import HttpTransport, ReplayTransport, RecordingTransport, build_transport

__all__ = [
    "Change", "ChatResult", "Charge", "OpsBudget", "SuperDocs", "SectionDiff",
    "SurgeryVerdict", "ApiError", "AuthError", "BudgetExceeded", "QuotaExhausted",
    "ReplayMiss", "SuperDocsError", "TransportError", "HttpTransport",
    "ReplayTransport", "RecordingTransport", "build_transport", "changes_from",
    "chunk_map", "deep_parse", "diff_chunks", "sha", "text_diff", "updated_html_from",
    "verify_surgical", "visible_text",
]
__version__ = "1.0.0"
