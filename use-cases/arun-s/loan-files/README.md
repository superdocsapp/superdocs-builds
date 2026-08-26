# Loan-file analyzer (vertical mini-app)

*Built by Arun S for the SuperDocs Round-2 task.* (Open-list family: **Vertical mini-apps**.)

A single-industry app: feed it a borrower's loan file — sanction letter, disbursement advice, salary
slip, EMI schedule — and it produces a grounded **loan decision memo**: is disbursal over the
sanctioned amount, and is the EMI affordable against income. Classification and the two rules are the
vertical's **data**, and the memo is handed to SuperDocs to export a branded one-pager.

## Run it (offline, no key)
```bash
python run_demo.py
python -m pytest tests/ -q     # 3 keyless tests
```
Sample output:
```
facts   : {sanctioned: 500000, disbursed: 520000, monthly_income: 60000, emi: 35000}
decision: REFER
  finding: Disbursed 520000 exceeds the sanctioned amount 500000
  finding: EMI 35000 is over 50% of monthly income 60000
```

## Files
| File | What it is |
|---|---|
| `analyze.py` | Classify each loan document → extract its amount → apply the two rules → decision. |
| `report.py` | Render the themed decision memo (HTML) + the SuperDocs export hand-off. |
| `sample_loan/` | A borrower's file (sanction, disbursement, salary, EMI). |
| `run_demo.py`, `tests/` | Offline demo + keyless tests. |

## Where this goes
A pull request into the public repository, **use-cases** folder. Secrets stay out of the code.
