# Task 2 — Job Architecture and Levelling Framework Builder



## Assigned build



Job architecture and levelling framework builder.



## Target users



HR, compensation, and people-strategy professionals who need to create and maintain consistent career architecture from existing job descriptions.



## Required outcomes



The application must transform job-description evidence into:



\- job families;

\- career tracks;

\- level definitions;

\- competency matrices by family;

\- employee-readable role profiles.



## Required behaviors



The system must:



1\. classify jobs using evidence rather than title matching alone;

2\. propose defensible job families and levels;

3\. preserve uncertain or conflicting cases as provisional or misfit;

4\. generate consistent framework and role-profile documents;

5\. preserve explicit human review;

6\. publish or export only after review;

7\. track dependencies between canonical level definitions and role profiles;

8\. propagate changes only to dependent content;

9\. preserve unrelated profile content during updates.



## Evidence dimensions



Classification and levelling should consider:



\- scope;

\- autonomy;

\- complexity;

\- organizational impact;

\- leadership;

\- management responsibility;

\- decision-making authority;

\- stakeholder breadth;

\- domain depth;

\- responsibility for outcomes.



Titles alone must never determine family or level.



## Required SuperDocs surfaces



The implementation must demonstrate real use of:



\- Multi-document

\- Search

\- Templates

\- Review

\- Export



## Acceptance criteria



### A1 — Defensible architecture



Families and levels must be grounded in role evidence and expose the reasoning behind assignments.



### A2 — Honest misfits



If evidence is insufficient, contradictory, or materially outside the proposed architecture, the role must remain provisional or misfit.



### A3 — Surgical propagation



Changing a canonical level definition must identify dependent profiles and propose only the required edits.



Unrelated profile content must remain unchanged.



### A4 — Human gate



Generated or proposed document changes must not become final without explicit review.



### A5 — SuperDocs integration



The project must demonstrably exercise upload, multi-document operation, search, templates, review/approval, and export.



### A6 — Production engineering



The project must include:



\- no secrets in source or history;

\- actionable failure handling;

\- safe retries or idempotency where needed;

\- progress visibility for long-running operations;

\- offline tests that do not require live credentials;

\- second-corpus validation;

\- measurable proof that unrelated document content is preserved.



## Non-goals



The mandatory build does not require:



\- HRIS integration;

\- ATS integration;

\- compensation benchmarking;

\- salary-band generation;

\- employee-record management;

\- authentication/RBAC platform;

\- generic document editing;

\- generic chatbot behavior;

\- real private HR data;

\- automatic approval;

\- automatic publication.
