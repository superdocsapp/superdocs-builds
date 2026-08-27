# Task 3 — Where SuperDocs sells

Ten use cases, each with named companies that would plausibly buy, the specific
role who owns the budget, and the wedge that gets you in the door.

**Two honesty notes up front.** I contacted nobody, as the brief requires — this
is desk research and reasoning, not outreach. And I know nobody personally at
any company named below; the brief says that is the normal answer, so I am
giving it straight rather than padding the list with weak connections.

The filter I applied throughout: SuperDocs edits documents in place, with
review. So the strongest buyers are teams where **the document already exists,
changes constantly, and a wrong change is expensive.** Generation-first use
cases are a worse fit — that problem is largely solved and the competition is
everyone.

---

## 1. Contract redlining against a playbook — in-house legal ops

**Who buys:** Head of Legal Operations. Budget usually already exists for CLM.

**Pain:** A counterparty returns a 60-page MSA with 40 changes. An associate
reads all 40 to find the 6 that breach the playbook. The work is not judgement,
it is scanning — and it is billed at judgement rates.

**Why SuperDocs specifically:** the output must be *the redlined contract*, not
a chat summary telling someone else to redline it. Targeted in-place edits with
per-change review is exactly the shape of this job.

**Named buyers:** Rippling, Ramp, Deel, Navan (fast-growing companies signing
high contract volume with small legal teams — the ratio that creates this pain).
Also DocuSign and Icertis as *partners* rather than customers: they own the
workflow and have no strong in-document editing agent.

**Wedge:** "Upload your playbook, upload a redline, get back the six clauses
that breach it, already marked up."

---

## 2. RFP and proposal response — bid teams

**Who buys:** VP Sales Operations, or Head of Bid Management.

**Pain:** Each RFP is 80% recycled from the last one, but the 20% that changes
is scattered through the document, and the recycled 80% carries last year's
client name, last year's pricing, and last year's compliance claims. Teams get
disqualified on the copy-paste errors, not the substance.

**Why SuperDocs:** this is a find-and-change-carefully problem across a long
document. Surgical precision with review is the product.

**Named buyers:** Accenture, Capgemini, Infosys, Wipro, Deloitte (bid factories
running hundreds of responses a quarter). Mid-market: Loopio and Responsive are
incumbents in RFP content management — again, better as channel than as target.

**Wedge:** last year's winning proposal + this year's RFP → a retargeted draft
with every changed claim flagged for a human.

---

## 3. Clinical trial protocol amendments — CROs and sponsors

**Who buys:** Head of Clinical Operations, or Regulatory Affairs Director.

**Pain:** A protocol amendment must propagate consistently into the Informed
Consent Form, the Investigator Brochure, the statistical analysis plan, and site
manuals. Miss one and you have a regulatory finding. Average protocol has 2–3
amendments; each costs real money and weeks.

**Why SuperDocs:** propagate one change into many documents, each edit reviewed
and attributable. High-consequence, human-gated, in-place.

**Named buyers:** IQVIA, Parexel, ICON plc, Syneos Health, Fortrea. Sponsor
side: Novartis, AstraZeneca, Biocon and Dr. Reddy's (the Indian pharma buyers
are a realistic first market given the company is India-registered).

**Caveat I would state to the buyer:** compliance certification is a roadmap
conversation, not a current fact. This segment will ask on the first call, and
the honest answer is the only one that survives their diligence.

---

## 4. Insurance policy wording and endorsements

**Who buys:** Head of Product (P&C), or Chief Underwriting Officer.

**Pain:** Policy wordings are versioned documents amended by endorsement.
Regulatory change in one state forces edits across dozens of wordings, and the
edits must be identical in meaning and traceable.

**Why SuperDocs:** near-identical to the contract case, but with a regulator
asking "show me every document this change touched."

**Named buyers:** ICICI Lombard, HDFC ERGO, Bajaj Allianz (India, reachable);
internationally Zurich, Chubb, Hiscox. Brokers too: Marsh, Aon.

---

## 5. Technical documentation that drifts from the code

**Who buys:** Head of Developer Experience, or Director of Technical Writing.

**Pain:** An API changes; twelve doc pages become subtly wrong. Nobody notices
until a customer files a ticket against a documented parameter that no longer
exists.

**Why SuperDocs:** the categories the brief says they keep wishing existed
include coding-tool integrations. A CI job that opens a PR against the docs when
the API surface changes, with each edit reviewed, is that product.

**Named buyers:** Stripe, Twilio, Postman, MongoDB, Snowflake — companies whose
documentation *is* the product surface. Also every mid-size API company that has
one technical writer and forty engineers.

**Wedge:** wire it to an OpenAPI diff. The trigger is free and the value is
immediate.

---

## 6. Annual reports, MD&A and regulatory filings

**Who buys:** Group Financial Controller, or Head of Investor Relations.

**Pain:** The annual report is assembled by twelve people, and the same number
appears in nine places. When a figure changes in the final week, someone updates
it manually everywhere and someone else misses one.

**Why SuperDocs:** consistency propagation with an audit trail, in a document
where an error is a restatement.

**Named buyers:** Infosys, TCS, HDFC Bank, Reliance (India, large IR functions);
service-side, the Big Four practices that produce these on behalf of clients.

**Important framing:** SuperDocs should detect and surface figures it cannot
independently verify, never assert them. The brief says builds are graded on
whether they *surface* unverifiable figures — that is exactly the right pitch
here, and it is also the honest one.

---

## 7. Grant applications and research administration

**Who buys:** Director of Research Development at a university, or Head of
Grants at a foundation.

**Pain:** The same research programme is submitted to six funders in six
different formats with six different page limits and six different framings.
Reformatting is done by postdocs who should be doing research.

**Why SuperDocs:** retarget an existing long document to a new template and
constraint set, with the researcher approving each change to their own science.

**Named buyers:** IITs and IISc (India), Wellcome Trust, Howard Hughes Medical
Institute, and the research offices of large universities — Oxford, Imperial,
Michigan.

**Note:** budget cycles here are slow and prices are low. Good logo, poor
first revenue. I would not start here.

---

## 8. Public-sector tendering and compliance responses

**Who buys:** Bid Director at a government contractor.

**Pain:** Public tenders are pass/fail on mechanical compliance — mandatory
clauses present, formatting exact, word limits respected. Excellent bids are
disqualified on formatting.

**Why SuperDocs:** a rules pack per tendering authority, applied to a document,
with findings pointing at the exact place. Configuration over code — a new
authority is a data change.

**Named buyers:** Serco, Capita, Leidos, L3Harris; in India, L&T and Tata
Projects.

---

## 9. Long-form book and series continuity

**Who buys:** Managing Editor at a publisher; also individual authors, though
they buy at a very different price.

**Pain:** The brief names this one directly — "a thousand-page book without
losing its context and its plotline." Continuity errors across a series are
caught by readers, not editors.

**Why SuperDocs:** the document is enormous, the edits are surgical, and the
author must approve every one. Nobody wants an AI rewriting their prose; they
want it to find where chapter 31 contradicts chapter 4.

**Named buyers:** Penguin Random House, HarperCollins, Wiley and Pearson
(education, where edition-to-edition updating is a standing cost centre).

**Honest read:** this is the most interesting use case on the list and the
hardest to monetise at first. Wiley and Pearson are the real buyers, because
textbook revision is a budgeted, repeating cost.

---

## 10. M&A disclosure schedules and diligence

**Who buys:** Partner in a corporate law practice, or Head of Corporate
Development.

**Pain:** Disclosure schedules are assembled under deadline from hundreds of
contracts, and each representation in the purchase agreement must be checked
against them. It is the most expensive document-scanning work in professional
services.

**Why SuperDocs:** cross-document consistency, with citations back to the
underlying contract. Every claim traceable is the whole requirement.

**Named buyers:** Cyril Amarchand Mangaldas, Khaitan & Co, AZB & Partners
(India); internationally Kirkland & Ellis, Latham & Watkins. Corp-dev side:
any serial acquirer — Thoma Bravo, Vista Equity portfolio companies.

---

---

## Five markets I would NOT chase, and why

These are the ones that look attractive on a slide and fail on contact. Each is
argued from the product's own stated boundaries or from who already owns the
workflow — not from taste.

**1. FP&A and financial modelling.** The deliverable is a model, and the rail is
explicit: reading a spreadsheet as a source is fine, but a product whose output
is an edited spreadsheet is not what SuperDocs is. Finance teams will ask for
exactly that within one meeting. *Evidence: the product's own stated
boundary.* The adjacent use case that does work is #6 — the annual report and
MD&A, where the output is prose.

**2. Real-time collaborative drafting.** Agencies, newsrooms, and anyone whose
pain is "three people editing at once." Live multiplayer with visible cursors is
explicitly not being built, and Google Docs already gives this away free. Any
deal here would be won on a feature that does not exist and is not planned.

**3. Enterprise content management.** The SharePoint-replacement conversation.
Buyers with this pain want an archive with permissions, retention and search —
and the rail is clear that SuperDocs edits and produces documents rather than
being the archive. These deals are large, slow, and would drag the roadmap
toward storage. Worth actively declining.

**4. Litigation e-discovery.** Tempting because the document volume is enormous
and the budgets are real. But the work is *read, classify and produce* — you
never edit evidence, because altering it is the one thing you must not do. The
product's edge is precise in-place editing with review, and that edge simply
does not apply. Relativity and Everlaw own the workflow with a decade of
case-law-shaped tooling. *This is the clearest poor fit on my list:* the better
the product gets at editing, the less relevant it is here.

**5. Anything gated on a certification today.** This one complicates my own #3
above, and I would rather say so than leave the list tidy. Clinical trials and
regulated pharma are a genuinely strong *fit* for the capability — propagate one
protocol amendment into many documents, each reviewed. But procurement in that
segment asks for the compliance framework on the first call, and the honest
answer is that certification is a roadmap conversation, not a current fact. So
the use case is real and the *sales motion* is blocked until that changes.
Selling into it now means either waiting out a long security review or implying
something untrue. I would keep it on the roadmap and off the pipeline.

The pattern across all five: SuperDocs wins where **the document already exists,
changes often, and a wrong change is expensive.** It loses where the output is
not a document, where the pain is concurrency, where the buyer wants storage, or
where editing is forbidden.

---

## Where these companies listen, and what opens the door

**Where they listen.** The technical buyers (#5 docs-drift, #10 diligence
tooling) are reachable where engineers already are — their own developer
communities, GitHub, and the tooling conversations on Hacker News and technical
newsletters. The operational buyers (#1 legal ops, #2 bid teams, #4 insurance)
do not read developer channels at all; they live in professional communities —
CLOC for legal ops, APMP for bid and proposal teams, and the vertical trade
press. The regulated buyers (#3, #6) are reachable almost exclusively through
industry conferences and existing vendor relationships.

**What opens the door.** Not a pitch — a document. The strongest opener for
every use case above is the same shape: *"send us one of your own contracts and
your playbook, and we will send back the clauses that breach it, marked up in
the document itself, in under a minute."* It works because it is falsifiable,
it costs the prospect nothing but one file, and it puts the product's actual
differentiator — the change landing in place, reviewed — in front of them
instead of describing it.

The second opener, for the developer segment specifically, is to make the
integration free to try: wire the docs-drift check to an OpenAPI diff so the
trigger costs nothing and the first useful result arrives before anyone has
spoken to sales.

**One thing I would not do:** lead with AI. Every one of these buyers has been
pitched an AI document tool this quarter. Leading with the review gate — *you
approve every change before it lands, and nothing you did not approve is
touched* — is the differentiated claim, and it is the one this product can
actually prove.

---

## If I had to pick one to build first

**Contract redlining (#1).** Not because it is the largest market, but because
it has the shortest demo: a playbook, a redline, and six flagged clauses in
under a minute, on a document the buyer brought themselves. It also produces the
cleanest measurable — clauses caught versus clauses a lawyer caught — which is
the kind of number that closes a deal without a pilot.

**The one I would build for love:** #5, the docs-drift integration, because the
trigger is free, the audience is developers who will try it without a sales
call, and it is the wedge into every engineering org.
