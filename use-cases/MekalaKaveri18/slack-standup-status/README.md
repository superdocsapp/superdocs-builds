# Slack standup → customer status memo

Built by **Mekala Kaveri** for the SuperDocs task.

**Kind:** extra from the open-list *class* (productivity tools people already live in). The shared open spreadsheet was not in this workspace; Slack-shaped standup → a CISO-forwardable status memo is that class. Duplicates are allowed.

**Who:** CSMs at B2B SaaS companies (think a Stripe or Atlassian customer-success pod). **Users you can name as a type:** Priya the CSM who must write something Harbor & Pine's CISO can read.

Slack thread is DATA. "Maybe Friday if we get lucky" does not ship. SuperDocs fills a status template; you approve and export.

```bash
cd use-cases/MekalaKaveri18/slack-standup-status
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8789
```

http://127.0.0.1:8789/ · `pytest -q` (no live key)

SuperDocs: templates, chat, approve, export. Built ON SuperDocs, not a clone.
