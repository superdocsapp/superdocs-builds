# Day-One Readiness Checklist — Project Northstar

Close is expected on 2026-03-01. Every item below must be true on that date.

| ID | Item | Owner | Status | Depends on |
| --- | --- | --- | --- | --- |
| DAY-FIN-1 | Opening balance sheet signed off by both CFOs | Finance & Accounting | in progress | — |
| DAY-FIN-2 | Payment runs for Northwind suppliers confirmed for week one | Finance & Accounting | not started | — |
| DAY-HR-1 | Every Northwind employee has a signed transfer letter | People & Organisation | in progress | — |
| DAY-HR-2 | All staff paid correctly from the acquirer payroll system | People & Organisation | not started | DEP-PAY |
| DAY-COM-1 | Top 20 customers have received a named-contact letter | Commercial & Customer | in progress | — |
| DAY-COM-2 | No customer contract lapses in the first 30 days | Commercial & Customer | not started | — |
| DAY-TEC-1 | All Northwind staff can authenticate against acquirer SSO | Technology & Data | not started | DEP-SSO |
| DAY-TEC-2 | Forecasting platform reachable from Meridian networks | Technology & Data | in progress | — |

## Items at Risk

These items depend on work that is not scheduled to complete before close:

* **DAY-HR-2** — All staff paid correctly from the acquirer payroll system. Depends on DEP-PAY (Payroll cutover from Workday to acquirer HRIS), owned by people, not due until month 2.
* **DAY-TEC-1** — All Northwind staff can authenticate against acquirer SSO. Depends on DEP-SSO (Single sign-on extended to all Northwind staff), owned by technology, not due until month 1.
