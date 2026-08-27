# Task 3 — Where SuperDocs Sells

Ten real-world use cases, grounded in what the product actually does (session-based chat editing, human-in-the-loop approval, multi-document sessions, attachments, image insertion, export with formatting control, MCP for agent-to-agent integration) — not generic "AI for documents" framing. For each: who buys it, why SuperDocs specifically fits, and named companies that would plausibly be real buyers. I don't have personal contacts at any of these — that's the normal, expected answer per the brief.

---

### 1. Vendor contract lifecycle management (procurement/legal ops teams)

**Who buys it:** Mid-size and large companies with a steady stream of vendor MSAs, amendments, and renewals — procurement or legal ops, not outside counsel.
**Why SuperDocs fits:** Upload a contract, ask for a targeted clause edit ("update the payment terms to Net 30 across this MSA"), review the diff, approve, export. The human-in-the-loop approval flow is the actual product-market fit here — legal teams won't accept a tool that silently rewrites a signed-adjacent document.
**Plausible buyers:** Deel, Ramp, Brex, Gusto (all fast-growing companies with heavy vendor-contract volume and in-house legal ops teams likely to adopt new tooling quickly).

### 2. Systematic review / evidence-synthesis packaging (this task's assigned build)

**Who buys it:** Academic research groups, CROs (contract research organizations), and medical-affairs teams at pharma companies preparing PRISMA-compliant systematic reviews for journal submission.
**Why SuperDocs fits:** Multi-document sessions (manuscript + extraction sheet + search strategy) plus image-attachment insertion (the flow diagram) plus targeted table insertion via chat — exactly the workflow this task's own assigned build proved out.
**Plausible buyers:** ICON plc, IQVIA, Labcorp Drug Development, a university research-methods core facility (e.g., Johns Hopkins Bloomberg School of Public Health's biostatistics center).

### 3. Loan file assembly and amendment tracking (commercial lending)

**Who buys it:** Regional and community banks' commercial lending departments, who assemble loan packages from a term sheet, credit memo, and covenant schedule, then amend them repeatedly as terms are renegotiated.
**Why SuperDocs fits:** The same "upload, targeted edit, approve, export" loop as vendor contracts, but the multi-document session matters more here — a loan file genuinely is several related documents that need to stay consistent with each other.
**Plausible buyers:** Live Oak Bank, Nav (SMB lending), Kabbage/Amex Business Blueprint's underwriting team.

### 4. Insurance claims documentation (claims adjusters)

**Who buys it:** Property & casualty insurers, where an adjuster assembles a claim file from an incident report, photos, an estimate, and correspondence, and needs a clean, consistent claim summary document.
**Why SuperDocs fits:** Image attachments aren't just for figures — the docs explicitly support vision use cases like "transcribe this photo/scan into the document," which maps directly onto claims work (damage photos, scanned handwritten incident reports).
**Plausible buyers:** Lemonade, Root Insurance, Hippo Insurance — all API-forward insurtechs likely to integrate rather than adopt a legacy seat-based tool.

### 5. Clinical trial site documentation (CRO / clinical operations)

**Who buys it:** Clinical operations teams managing informed-consent forms, protocol amendments, and site-specific regulatory documents across many trial sites, where a protocol change needs to propagate as a targeted edit to every site's consent form without touching unrelated sections.
**Why SuperDocs fits:** "An update should cost like an update" — the core design principle Task 1 was built around — is exactly the pain point here: a single protocol amendment shouldn't require manually re-editing 40 site documents from scratch.
**Plausible buyers:** IQVIA, Parexel, Medpace, a hospital system's clinical trials office (e.g., MD Anderson's clinical research administration).

### 6. Real estate transaction document assembly (title/escrow)

**Who buys it:** Title companies and escrow agents assembling closing packages from a purchase agreement, disclosures, and lender documents, where small last-minute changes (a closing date, a name spelling) need to propagate correctly without a full re-draft.
**Why SuperDocs fits:** Template support plus targeted, reviewed edits — a closing package is largely boilerplate with a handful of transaction-specific details that must be exactly right, which is a good match for "AI proposes the specific change, human confirms it."
**Plausible buyers:** Opendoor, Better.com's title/escrow arm, First American Title.

### 7. HR policy and offer-letter management (people ops)

**Who buys it:** Mid-size companies' HR/people teams maintaining employee handbooks, offer letters, and policy documents across jurisdictions, where a benefits change needs to be reflected consistently across every state-specific policy variant.
**Why SuperDocs fits:** Session-based editing with export-per-variant is a natural fit for "same base document, many small jurisdictional deltas" — a very different shape of multi-document problem than the contract-amendment case, showing the product's range.
**Plausible buyers:** Rippling, Gusto, Justworks.

### 8. Long-manuscript editing with context continuity (independent authors, small presses)

**Who buys it:** Individual authors and small publishing houses editing a long manuscript (100k+ words) who need targeted line edits without losing track of established plot/character facts elsewhere in the book.
**Why SuperDocs fits:** This is explicitly one of the categories the brief itself names as a wished-for use case ("helps someone write and manage a thousand-page book without losing its context and its plotline"), and SuperDocs' stated document-scale limits (up to roughly 6,000 pages per document) suggest this is a genuinely supported scale, not a stretch.
**Plausible buyers:** Reedsy (a marketplace connecting authors with editors — a plausible integration partner), a small independent press (e.g., Graywolf Press, Coffee House Press), or directly to prolific self-published authors via a consumer-facing tier.

### 9. Financial audit workpaper assembly (accounting firms)

**Who buys it:** Mid-market accounting/audit firms assembling audit workpapers that reference a client's financial statements, a sampling methodology, and testing results, where a single corrected figure needs to propagate to every workpaper that cites it.
**Why SuperDocs fits:** The "never bluffs, traces every claim to its source" principle Task 1 was built around is exactly what an audit workpaper needs — the value proposition isn't speed alone, it's defensible traceability, which is a harder and more valuable sell to this buyer than to most.
**Plausible buyers:** BDO, RSM, Baker Tilly — mid-market audit firms below the Big Four, generally more willing to adopt new tooling than the largest firms.

### 10. Grant proposal assembly (research administration offices)

**Who buys it:** University research administration offices and nonprofit grant-writing teams assembling NIH/NSF-style proposals from a narrative, a budget justification, a biosketch, and a data-management plan — several related documents that must stay consistent and meet strict formatting/page-limit rules.
**Why SuperDocs fits:** Multi-document sessions plus export formatting control (paper size, margins) map directly onto federal grant formatting requirements, and the checklist/page-reference problem from Task 2's own build is structurally identical to grant compliance-checklist requirements.
**Plausible buyers:** A university's office of sponsored programs (e.g., University of Michigan's Office of Research), RAND Corporation, Instrumentl (a grant-discovery platform — plausible integration partner).

---

**Note on companies named above:** these are informed guesses about who would plausibly buy this, based on company size, document-heavy operations, and (where relevant) existing API-forward posture — not confirmed leads. I have no personal contacts at any of them; per the brief, that's the normal answer, and I have not and will not reach out to any of them myself.