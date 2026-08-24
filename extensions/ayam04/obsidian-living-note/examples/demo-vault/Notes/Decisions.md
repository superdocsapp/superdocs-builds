# Decisions

**14 August 2026 — one importer, not two.** We merged the CSV and EDI paths into a single importer. Reason: two paths meant two sets of edge cases and the EDI volume is 3% of the total.

**16 August 2026 — Postgres 16, not 17.** 17 is not yet supported by the managed provider we are on. Revisit in January.

**Open — who owns the reconciliation screen after launch?** Raised on 12 August, still not decided.
