# Task 2: Community Launch Plan & Distribution Strategy

> **Assigned Build**: Resource-first launch into a practitioner community  
> **Resource**: *The Pre-Submission Peer-Review & Manuscript Audit Dossier*  
> **Guiding Principle**: *The resource must be good enough that the community keeps it even with all vendor mentions stripped, and the affiliation disclosure must sit right at the top.*

---

## 1. Target Community Profile & Rule Audit

### Primary Launch Community: **r/MachineLearning & r/PhD (Reddit) + Hugging Face Discord / Open Science Slack**
- **Audience Size**: ~3.2M combined active researchers, graduate students, and industry AI practitioners.
- **Vibe & Culture**: Highly skeptical of commercial promotion, hostile to generic marketing tools, but deeply appreciative of open-source frameworks, preprint checklists, and workflow optimizations that save them from desk rejections.

### Written Rules Audit & Compliance Analysis
- **r/MachineLearning Rule 4 (No Commercial Self-Promotion / Low-Effort Tool Shilling)**:
  - *Rule Text*: Direct commercial links and vendor pitches without substantial technical contribution are removed immediately by moderators.
  - *Compliance Plan*: We do NOT link to a signup page or gate the resource behind an email capture. The full markdown text is delivered directly inside the post and in a public GitHub Gist / PDF export.
- **Disclosure Rule**:
  - *Compliance Plan*: Upfront, transparent disclosure in paragraph 1 stating who made it and why.

---

## 2. Launch Copy & Introduction Asset

### Post Title
`[Resource] Pre-Submission Peer-Review & Parameter Consistency Audit Pack (Markdown / LaTeX / Checklist)`

### Exact Post Copy (Including Upfront Disclosure)
```markdown
Hi everyone,

**Affiliation Disclosure**: I am a growth engineer working on SuperDocs (an in-document AI editing tool). We built this pre-submission audit template internally to help our research collaborators catch multi-section parameter drift, unanchored abstract claims, and broken citations before journal submission. 

This entire pack is 100% free, un-gated, and open-source. You don't need an account, you don't need to sign up for anything, and you can copy the raw markdown directly below to use in Overleaf, Obsidian, Google Docs, or whatever you write in.

---

### Why We Made This
When you have 4–6 co-authors working across 40+ pages, minor revisions create invisible drift:
1. Section 3 updates a learning rate or batch size, but Section 6 (Ablations) still lists the old run.
2. The Abstract claims a 45% latency speedup, but the Results table only demonstrates throughput without latency confidence intervals.
3. Citation keys get orphaned after major structural cuts.

### What is Inside the Pack:
1. **Abstract Claim Verification Matrix**: Maps every quantitative claim to exact table/figure coordinates and statistical p-values.
2. **Cross-Section Parameter Sync Table**: A structured schema to verify that hyperparameters, dataset sample counts (N), and compute topologies match across all sections.
3. **Reviewer Defense Matrix**: A pre-flight stress test for common reviewer pushbacks (ablation coverage, baseline fairness, reproducibility).
4. **Citation Integrity Checklist**: Verifies DOI resolution and prior art fairness.
5. **Data & Ethics Compliance Gate**: Hard-blocks submission if Data Availability Statements (DAS) or IRB approvals are missing, preventing immediate desk rejections from top-tier journals.

[Raw Markdown Pack below...]
```

---

## 3. What is Said vs. What is Deliberately Left Unsaid

| Topic | What is Stated Explicitly | What is Deliberately Left Unsaid |
|---|---|---|
| **Author Affiliation** | *"Built by Rohit @ SuperDocs as a free open-source contribution."* | No hard sales pitch, no "try SuperDocs today", no discount codes, no marketing buzzwords ("revolutionary", "all-in-one"). |
| **Tool Usability** | *"Use this in whatever editor you prefer: Overleaf, Markdown, Notion, or Google Docs."* | Never claiming existing tools are "terrible" or demanding they switch their whole workflow immediately. |
| **Product Feature Connection** | Included subtle SuperDocs in-document refactor prompts as optional copy-paste snippets. | No unsolicited follow-up DMs to commenters. |

---

## 4. 48-Hour Inbound Community Q&A Playbook

When practitioners engage in the comments, the response strategy focuses purely on scientific utility:

### Scenario A: A user asks, *"How do you handle synchronizing parameter changes across a 60-page LaTeX draft without doing it by hand?"*
- **Response**: *"In standard workflows, people grep for variable names or use search-and-replace (which breaks if the parameter syntax varies). In SuperDocs, we built multi-section targeted editing so you can select the Abstract, Methodology, and Appendix simultaneously and instruct the model to reconcile references directly in-place without re-pasting. But if you're in pure Overleaf, we recommend defining LaTeX macros for key numbers (e.g. `\newcommand{\modelparam}{...}`) at the top of your preamble so updates propagate automatically."*
- **Why this works**: Answers the question technically, provides immediate standalone value (LaTeX macro tip), and naturally illustrates the exact problem SuperDocs solves.

### Scenario B: A user asks, *"Can I use this for NIH / NSF grant applications?"*
- **Response**: *"Yes! In fact, Section 2 (Parameter Sync) and the Budget Justification cross-check were designed specifically around SBIR and NIH R01 review criteria where budget-to-methodology mismatches cause instant score penalties."*

### Scenario C: A user asks, *"Journals are getting super strict about Data Availability Statements (DAS). Does this cover that?"*
- **Response**: *"Exactly why we added Section 3 (Pre-Flight Reproducibility & Data Compliance). Nature and IEEE are issuing massive desk rejections right now for papers that don't explicitly link their DAS to a public Zenodo/OSF repo in the methodology. The dossier treats missing DAS or IRB approvals as a hard blocker so you don't waste 3 weeks in the submission queue just to get kicked back."*

---

## 5. Conversion Tracking & Downstream Inbound Loop

- **Primary Destination**: A clean, un-gated GitHub repository / preview page with 1-click "Open in SuperDocs" or "Download Markdown".
- **Attribution Model**: UTM parameter tracking on the open-source repo badge (`utm_source=reddit_r_ml&utm_medium=practitioner_resource&utm_campaign=peer_review_dossier`).
- **Success Metric**: Number of markdown downloads and organic in-document template forks.
