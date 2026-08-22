# CRM → Proposal → E-Sign Pipeline

SuperDocs Round 2, Task 2 — second assigned build (S3). Pulls a deal's fields from a CRM, populates a
SuperDocs proposal template with real branding and terms, gates the draft behind human approval, then hands
the approved document to DocuSign's real MCP server to route for signature. SuperDocs' role stops at
generating and formatting the document — sending it out and confirming execution is entirely DocuSign's job,
never claimed as SuperDocs' own.

## Pipeline

```
CRM deal record (fictional/synthetic, per task rules)
        │
        ▼
proposal_engine.py ── builds a SuperDocs session from a proposal TEMPLATE, populates it with the deal's
                       fields (client name, deal value, terms, branding) via a scoped chat instruction
        │
        ▼
    human review   ── the draft is shown before anything is sent anywhere; approve or reject
        │
        ▼ (approved only)
  export as PDF    ── SuperDocs exports the finished, formatted document
        │
        ▼
 DocuSign MCP call ── the exported PDF is handed to DocuSign's OWN MCP server
                       (sandbox: https://mcp-d.docusign.com/mcp) to create and send an envelope for
                       signature. This is a real call into DocuSign's real, documented MCP server -- not a
                       stub -- once real DocuSign developer credentials are configured (see below).
```

## Why DocuSign, and why real (not stubbed)

DocuSign publishes an official MCP server, confirmed via their own developer docs: production at
`https://mcp.docusign.com/mcp`, and a free developer sandbox at `https://mcp-d.docusign.com/mcp`. Sandbox
accounts are free, don't expire, and documents sent through them are explicitly not legally binding (test
stamps) — exactly the kind of safe environment the task's "should not cost you real money" rule wants.

This build's `DocuSignMCPClient` (`src/esign_client.py`) makes a genuine MCP client connection to that
server and calls its real `create_envelope`-equivalent tool. It is NOT a hand-rolled stub pretending to be
DocuSign.

## What's tested without a live key

Everything up to and including the human-approval gate is tested against `FakeSuperDocsClient` (same pattern
as Build A) and `FakeEsignProvider` — no live key of any kind required. This proves: the proposal is
correctly populated from CRM fields, nothing is sent anywhere without approval, and a rejected proposal never
reaches the e-sign step at all.

**What genuinely needs a live DocuSign developer account to verify further:** the actual OAuth handshake and
the real envelope-creation call. `DocuSignMCPClient` is written against DocuSign's documented MCP protocol
and endpoint, but I do not have DocuSign credentials to run it against the live sandbox myself. This is
logged honestly rather than faked — see "What's honestly a gap" below. Once you (Meethu) create a free
DocuSign developer account and set `DOCUSIGN_ACCESS_TOKEN` / `DOCUSIGN_ACCOUNT_ID` in `.env`, `src/cli.py
send` runs the real end-to-end call.

## What's honestly a gap

- DocuSign's OAuth setup (Integration Key + JWT Grant or Authorization Code flow, plus account-specific base
  URI discovery after auth) is real friction their own developers describe as non-trivial for multi-user
  setups. This build assumes a single already-obtained access token supplied via environment variable rather
  than implementing the full OAuth dance itself — a reasonable scope cut for a weekend build, logged rather
  than hidden. A production version would need the full OAuth flow, likely via DocuSign's own quickstart
  SDK rather than hand-rolled.
- The CRM is entirely synthetic (a Python dict of fictional deals), per the task's own rule that fictional
  clients and fabricated test data are expected and real third-party data is not welcome. A real deployment
  would integrate an actual CRM's API (Salesforce, HubSpot) instead.
- I have not personally run the DocuSign leg against a live sandbox account — this needs your credentials,
  not mine, and is exactly the part the demo video should show working live.
