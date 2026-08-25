# Twilio SMS → SuperDocs document bridge

An SMS-only document assistant for teams with limited smartphone data. A person
texts an instruction and a public document URL to a Twilio number; this service
downloads the file, uses the SuperDocs API to edit or generate content, exports
the result, and sends a single SMS back with a download link.

## SMS format

```
EDIT PDF https://public.example.org/field-report.docx :: add a one-paragraph executive summary
CREATE DOCX :: draft a one-page weekly field report template for a water project
```

`EDIT` requires a public HTTPS document URL. `CREATE` makes a new document from
the instruction. Supported result formats: `PDF`, `DOCX`, `HTML`, `MARKDOWN`,
and `TXT`.

## SuperDocs features used

- `POST /v1/documents/upload` imports the referenced document into a stable SMS
  session.
- `POST /v1/chat` applies the natural-language instruction with
  `approval_mode=approve_all`; this is appropriate for a one-step SMS bridge.
- `POST /v1/documents/export` produces the requested file format.

## Run locally

Requirements: Node.js 20+, a SuperDocs API key, Twilio test credentials/number,
and a public HTTPS tunnel such as ngrok or Cloudflare Tunnel.

```bash
cd use-cases/oviya12/Twilio-SMS-DOC-bridge
npm install
cp .env.example .env
# Fill in .env. PUBLIC_BASE_URL must be your public HTTPS tunnel URL.
npm test
npm start
```

In Twilio Console, set your test number's **Messaging → A message comes in**
webhook to:

```
https://your-public-host.example/twilio/inbound
```

Use `GET /health` to confirm the service is live. In production, deploy this
service behind HTTPS; `/files/*` is the public URL sent in the SMS.

## Proving the flow

Text the configured Twilio number:

```
EDIT PDF https://your-public-file.example/sample.docx :: add a three-bullet summary at the top
```

The terminal emits structured log events containing `messageSid`, `from`, and
the inbound `body` (set `LOG_MESSAGE_BODY=false` if message contents must not be
logged). The reply SMS contains the resulting public file URL. Twilio retries are
deduplicated in memory by `MessageSid`.

## Security and production notes

- Twilio request-signature validation is on by default; only disable it for a
  local test.
- Only public HTTPS document links are accepted. The downloader rejects common
  private-network addresses, caps downloads at 10 MB, validates redirects, and
  applies timeouts.
- Never commit `.env`; it contains Twilio and SuperDocs credentials.
- The in-memory retry guard is sufficient for a demo. Use Redis/a durable queue
  before multi-instance production deployment.
- A public result link requires hosting this service and its `results/` directory
  on durable public storage. Replace local storage with S3/R2 for production.

## Demo

Run `npm test`, start the service behind a public HTTPS URL, then send the sample
SMS above. Show the `sms.received` and `sms.completed` JSON log lines alongside
the single Twilio reply. This makes the inbound `From`/`Body` pair traceable
without exposing API credentials.
