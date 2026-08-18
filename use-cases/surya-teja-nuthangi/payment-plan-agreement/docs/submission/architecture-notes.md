# Architecture notes

```text
User -> Payment Terms UI -> Deterministic PaymentPlan Engine
  -> Canonical Facts + Schedule Projection + Prose Projection
  -> Verified Agreement Seed -> SuperDocs Async Adapter
  -> Proposed Changes -> Independent Pre-approval Verifier
  -> Human Item Review Gate -> Final Document
  -> Independent Final Verification -> DOCX Export
```

A blocked proposal is rejected or receives one narrow repair request before returning through review. The API key exists only in the Python server process, and generation occurs only after an explicit click.
