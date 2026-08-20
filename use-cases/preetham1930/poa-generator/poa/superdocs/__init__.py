"""The SuperDocs surface: transport, client, decision ledger, verifier.

Copied from `builds/statutory-statements/statutory/superdocs/` and rebuilt
(Decision 31). The one divergence is the export gate - `PoaClient.export`
requires a `NoticeReceipt` - and it is the reason this build exists.
"""

from __future__ import annotations
