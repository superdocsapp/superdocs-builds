"""Runbook Reconciler.

Infrastructure config is ground truth; runbooks in Confluence are checked
against it; findings go to a human; approved fixes land as surgical edits to the
exact passage with everything else on the page provably untouched.

The hard boundary, stated once here because it constrains every module below it:
**this reads DevOps files and writes documents, and never the other way round.**
A finding about a wrong Terraform value produces a ticket suggestion, never a
write to Terraform.
"""

from __future__ import annotations

__version__ = "0.1.0"
