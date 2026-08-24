# SuperDocs integration

This use case keeps the SuperDocs boundary server-side and makes the document workflow explicit:

1. Prepare the translation packet and clean source HTML.
2. Authenticate with `SUPERDOCS_API_KEY` on the server only.
3. Attempt the explicit document upload surface for compatibility with the original task contract.
4. Run the HTML-first `/v1/chat/async` workflow with `approval_mode: "ask_every_time"`.
5. Poll `/v1/jobs/{job_id}` until SuperDocs reaches `awaiting_approval` or `completed`.
6. Show proposed changes to the human reviewer.
7. POST per-change decisions to `/v1/chat/{session_id}/approve`.
8. Export the reviewed DOCX through `/v1/documents/export`.
9. Verify that `data-chunk-id` anchors survive the SuperDocs round trip.

The current SuperDocs integration guidance describes HTML in/out, server-side API-key handling, asynchronous jobs, human approval and chunk-id preservation as the core integration contract. See the official documentation: https://docs.superdocs.app/guides/integration-starter-prompt

## Important response handling

The integration deliberately keeps the documented double-JSON proposed-change parser in `src/superdocs/client.ts`. A proposed-change payload may require parsing the outer JSON and then parsing the `content` JSON string before accessing `change_id`, `chunk_id`, `old_html`, `new_html`, and the explanation.

Approval also preserves the required top-level `approved` field plus per-change decisions.

## Credentials

Create `.env` from `.env.example`:

```text
SUPERDOCS_API_KEY=sk_...
```

The server loads `.env` locally. The key is never returned by an API route and never embedded in browser JavaScript.

## Live UI flow

Run:

```bash
npm start
```

Open `http://localhost:8787` and:

- Analyze a manuscript.
- Approve the evidence-backed terms you want enforced.
- Check **Live SuperDocs**.
- Send the packet with a narrowly scoped instruction.
- Review the proposed changes shown by the UI.
- Approve/reject each change.
- Export the reviewed DOCX.

A live credentialed run is the only evidence that can mark the API round trip as verified. Mock tests never claim live success.
