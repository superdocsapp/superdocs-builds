"""`builds/poa-generator/` - card S2, the power-of-attorney generator.

A guided intake picks clauses out of a data library; we assemble the whole draft
and upload it verbatim; SuperDocs fills in the party-specific and power-specific
chunks one at a time, each verified by reading the whole document back; and the
document is not exportable until both notices have been read back verbatim.

Nothing in this package imports from `system/` (`tests/test_isolation.py`), and
nothing in it speaks `system/`'s outcome vocabulary
(`tests/test_domain_boundary.py`). Ideas are copied from
`builds/statutory-statements/`, never imported (Decision 31).
"""

from __future__ import annotations
