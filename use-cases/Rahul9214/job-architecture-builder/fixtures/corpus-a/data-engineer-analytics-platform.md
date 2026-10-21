# Data Engineer, Analytics Platform

## Team
Data Platform

## Role purpose
Build the pipelines and warehouse models that let Northstar teams analyze product and revenue data without each maintaining a private extract.

## Responsibilities
- Design and operate ingestion from production databases and event streams into the warehouse.
- Model core entities (accounts, workspaces, invoices) for analysts and data scientists.
- Enforce data contracts with producing teams when schemas change.
- Keep freshness and quality monitors green; page yourself when a critical table is late.
- Optimize warehouse cost and query performance for the most-used marts.
- Document datasets so a new analyst can find the grain and the caveats.
- Partner with Finance on revenue tables that must match the ledger within a defined tolerance.

## Scope and autonomy
You own named pipelines and marts, not every dashboard in the company. Modeling choices inside your domain are yours, reviewed by the staff data engineer for cross-domain keys. You do not set company metrics definitions; you implement the ones Product and Finance agree on.

## Leadership and management
No direct reports. You review other data engineers' modeling PRs. You do not hire or rate people.

## Stakeholders
- Analytics engineers and data scientists who query your tables
- Backend engineers whose services emit events
- Finance, for revenue reconciliation
- Privacy and security, for retention and access
- Your data-platform manager

## Requirements
- Production experience with warehouses, orchestration, and incremental pipelines.
- Careful handling of late-arriving data and slowly changing dimensions.
- Ability to explain grain, keys, and caveats in writing.
- Comfort with SQL and at least one transformation framework.
