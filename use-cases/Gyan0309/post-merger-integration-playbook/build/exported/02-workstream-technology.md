# Technology & Data Workstream Charter — Project Northstar

**Lead:** S. Bhattacharya

**Deal:** Meridian Retail Group acquires Northwind Analytics LLC

**Expected close:** 2026-03-01

## 1. Scope

Platform integration, Snowflake consolidation, access management, and decommissioning the retired systems.

## 2. Synergies Owned

| ID | Description | Annual value | Realised by |
| --- | --- | --- | --- |
| SYN-T1 | Terminate the external analytics vendor contracts and platforms | $1,520,000 | month 7 |

**Total claimed: $1,520,000**

## 3. Dependencies Owned

| ID | Description | Needed by | Consumed by |
| --- | --- | --- | --- |
| DEP-CRM-MIGRATION | Migrate CRM records from Northwind into acquirer Salesforce | month 4 | commercial |
| DEP-SSO | Single sign-on extended to all Northwind staff | month 1 | people, commercial |

## 4. Day-One Readiness

| ID | Item | Status | Depends on |
| --- | --- | --- | --- |
| DAY-TEC-1 | All Northwind staff can authenticate against acquirer SSO | not started | DEP-SSO |
| DAY-TEC-2 | Forecasting platform reachable from Meridian networks | in progress | — |

## 5. Open Cross-Workstream Conflicts

* **[HIGH] Day-one item DAY-TEC-1 depends on work not delivered until month 1.** technology lists DAY-TEC-1 (All Northwind staff can authenticate against acquirer SSO) as a day-one readiness item, but it depends on DEP-SSO (Single sign-on extended to all Northwind staff), which technology does not deliver until month 1. The item cannot be green at close. Either pull the dependency forward or move the item out of day one. This document's stake in it: DEP-SSO: Single sign-on extended to all Northwind staff (month 1).
* **[HIGH] commercial and technology both own the same dependency.** commercial owns DEP-CRM (Migrate Northwind CRM records into the acquirer Salesforce instance, needed by month 4) and technology owns DEP-CRM-MIGRATION (Migrate CRM records from Northwind into acquirer Salesforce, needed by month 4). Two owners means each side can reasonably assume the other is delivering it. Assign one. This document's stake in it: DEP-CRM-MIGRATION: Migrate CRM records from Northwind into acquirer Salesforce (month 4).
* **[HIGH] finance and technology both claim the same synergy.** finance claims SYN-F2 (Terminate external analytics vendor contracts, $1,800,000) and technology claims SYN-T1 (Terminate the external analytics vendor contracts and platforms, $1,520,000). These describe the same saving, so the integration total is overstated by up to $1,520,000. One workstream must own it and the other must drop the claim. This document's stake in it: SYN-T1: Terminate the external analytics vendor contracts and platforms ($1,520,000).
* **[MEDIUM] Workstream synergy claims exceed the deal target.** Workstreams claim $5,150,000 in total against a deal target of $4,600,000 — an excess of $550,000 (12%). Either the target is stale or some claims are double-counted. Reconcile before the tracker goes to steering. This document's stake in it: claims $1,520,000.
