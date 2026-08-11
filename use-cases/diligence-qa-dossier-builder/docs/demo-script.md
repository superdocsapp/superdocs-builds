# SuperDocs Demo Script: Diligence Q&A Dossier Builder

**Target Duration**: 3 Minutes
**Audience**: Recruiters, Founders, and Engineering Reviewers

---

## [0:00 - 0:30] Introduction & Data Room Overview
* **Action**: Open the React Dashboard (`http://localhost:5173`) in the browser. Show the main dashboard view.
* **Script**: 
  > "Welcome. I am demonstrating the Diligence Q&A Dossier Builder. We are looking at the main dashboard in Founder Mode.
  > First, let's navigate to the **Data Room** tab. Here, you can see our ingested due diligence documents. We have uploaded six core files covering Acme AI's overview, financials, customer contracts, legal reviews, and operation risks.
  > Let's look at the document list: we have clean SHA-256 deduplication and support for mixed formats (TXT, PDF, DOCX, XLSX). Ingestion is fully complete and indexed in our pgvector database."

## [0:30 - 1:15] Creating a Dossier & Core QA
* **Action**: Click the **Create Dossier** button. Enter dossier name: `Acme AI Acquisition Audit`.
* **Action**: Click the checkbox for all 6 default diligence questions:
  1. *What was the company's FY2025 ARR?*
  2. *What is the company's current employee count?*
  3. *What was the company's FY2025 gross margin?*
  4. *Who are the company's major customers?*
  5. *What security certifications does the company have?*
  6. *What are the company's main legal or operational risks?*
* **Action**: Click **Launch Dossier**. Show the dossier in a `running` state.
* **Script**: 
  > "I will now create a new diligence dossier named 'Acme AI Acquisition Audit' and select our six core diligence questions.
  > Once launched, the LangGraph workflow runs these questions sequentially and isolated. It parses query intent, retrieves context via pgvector, and passes it through an evidence-grounded logic check."

## [1:15 - 2:00] Finding Verification & Conflict Resolution
* **Action**: Show that 5 out of 6 findings are marked `answered` with high confidence scores. 
* **Action**: Scroll down to Question 1: *What was the company's FY2025 ARR?* Note that the status is `conflict` and review status is `pending`.
* **Action**: Click to expand Question 1. Show the comparative columns listing the supporting document (`02_financials.txt` listing $2.4M ARR) alongside the contradicting document (`06_conflicting_statement.txt` listing $3.1M ARR).
* **Script**: 
  > "As you can see, 5 questions have been successfully answered with no false ARR conflicts. However, for Question 1 about ARR, the system detected a direct conflict: our financials show $2.4M ARR, while our secondary statement shows $3.1M. 
  > Because a conflict was detected, the workflow immediately suspended execution, set confidence to 10%, and routed the thread to `pending` review."

## [2:00 - 2:30] Human-in-the-Loop & Governance Actions
* **Action**: In the human review panel, click **Edit Draft Answer**. Overwrite the answer text with: `"The company has a conflict of $2.4M vs $3.1M ARR. Verified financials indicate $2.4M."` Click **Approve & Resume**.
* **Action**: Show the dossier status transition to `completed`. Expand Question 1 to show the edited answer and the archived execution history trail.
* **Script**: 
  > "As the diligence manager, I can choose to approve, edit, reject, or retry. I will edit the draft answer to state that financials indicate $2.4M, then approve.
  > The LangGraph checkpointer resumes the thread, saves the change, logs the action to our execution audit history, and marks the dossier as fully finalized."

## [2:30 - 3:00] Investor Mode & Export
* **Action**: Click the **Investor/Founder Toggle** in the navigation header. Show the read-only view.
* **Action**: Show the **Diligence Gaps** list, the **Needs Review** counts, and the **Estimated Telemetry Costs** card.
* **Action**: Click **Export Dossier** to compile and download the Markdown report. Show the secure-sharing disclaimer at the bottom of the page.
* **Script**: 
  > "Finally, let's toggle to **Investor Mode**. This switches the dashboard to a read-only, risk-centric interface. Investors can immediately view critical diligence gaps, unresolved conflicts, and cost estimates (estimated token usage and API pricing). 
  > With a single click, we can export the completed dossier report containing our grounded answers, exact citations, and audit history.
  > Thank you! That concludes our walk-through."
