# Concise narration script

**Approximate spoken time:** 2:35–3:00 at a calm pace. The visual shot list supplies the timestamps.

Release decisions are often assembled from requirements, design notes, test evidence, and checklists. The user needs a cited answer and a safe review gate, not a summary that cannot be audited.

First, the SuperDocs CLI handles a small synthetic document from a pipe. `sdx new` accepts stdin, keeps the requested title, and the offline fixture flow produces structurally valid PDF and DOCX exports. This recording makes no live API call.

Now the edit is started in review mode. JSON mode emits one schema-version-1.0 object, reports pending changes, and exits with the documented pending status without prompting. Human mode shows each section-level proposal: its heading, change ID, operation, explanation, old text, and new text.

Approval is explicit. The user accepts one change and rejects another with feedback. The command rejects incomplete, duplicate, conflicting, or unknown IDs; no proposal lands without a decision. The final offline export is verified.

The Release Readiness Analyst then ingests the synthetic release bundle. Its six durable stages make ingestion, provenance, analysis, policy, review, and reporting visible. A finding shows its source name, SHA-256, line range, and quoted evidence. A sentence embedded in a document that asks the system to ignore its rules is treated as untrusted content; it cannot alter policy or tools.

The review branch requires item-level decisions. One finding is rejected with feedback and another approved. The incomplete state remains pending until every item has a decision.

Next, deterministic fault injection stops the process after a checkpoint. A new process resumes the same run identifier and continues; it does not create a replacement run. This is offline restart testing, not a claim about a live service.

When new synthetic test evidence arrives, the report gets a new revision. Dependent findings change, while an unaffected finding keeps its identity and citation. The final card shows a completed run, six stages, three cited findings, and all decisions recorded. The policy verdict is blocked because the fixture intentionally contains critical unresolved evidence; that is the safe result.

The evidence shown here is offline. There was no live operation in this recording, no live cassette, and no renderer-based 120-page count. The supplied Task 4 PDF was unavailable, so exact PDF wording still requires confirmation before submission.
