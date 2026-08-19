# Chat to SuperDocs

Created by **Abhinav Choudhary**.

Chat to SuperDocs is a Chrome/Chromium extension that takes the latest completed answer from ChatGPT or Claude and turns it into a growing, reviewable SuperDocs document. It keeps the answer's headings, nested lists, tables, code blocks, and math markup; starts from a small template; and can append later captures to the same document.

The extension proves the reviewable SuperDocs workflow:

1. Captures a completed answer from `chatgpt.com` or `claude.ai`.
2. Creates a document HTML payload from a template, or reuses the approved active document in append mode.
3. Sends a `chat/async` edit instruction with `ask_every_time` approval.
4. Polls while the job is `pending` or `in_progress`, then shows every pending item for individual approval or rejection.
5. Stores the returned HTML only after completion and exports it as DOCX.

## Why a local bridge?

SuperDocs API keys must remain server-side. This extension never reads, stores, or sends an API key. Instead, a tiny localhost bridge receives extension requests and adds the key from its own environment before calling SuperDocs. The bridge accepts requests only from the specific extension origin you configure.

## Run it

Requirements: Node 18+ and a SuperDocs API key. Do not put the key in this repository or in the extension.

1. Load the extension:
   - Open `chrome://extensions` (or Chromium equivalent), enable **Developer mode**, and choose **Load unpacked**.
   - Select this `chat-to-superdocs` directory.
   - Copy the extension ID shown by Chrome.
2. Start the local bridge from this directory, replacing the placeholders in your shell only:

   ```sh
   SUPERDOCS_API_KEY=sk_your-key-here \
   ALLOWED_EXTENSION_ORIGIN=chrome-extension://your-extension-id \
   node bridge/server.mjs
   ```

3. Open a completed ChatGPT or Claude answer and select the extension icon.
4. Choose **Capture latest answer**, select a template or append mode, then choose **Send for review**.
5. Approve or reject each proposed change and, once processing finishes, choose **Export DOCX**.

The options page deliberately permits only `http://127.0.0.1:8787` in this first draft. It avoids silently sending document content to an arbitrary endpoint.

## Test

```sh
npm test
```

The tests are offline and cover rich-structure preservation in the document envelope, append-mode safeguards, the required double JSON parse of proposed-change events, processing/review state, item-level decisions, and completed-document extraction.

## SuperDocs features used

- Async chat editing (`POST /v1/chat/async`)
- Job polling (`GET /v1/jobs/{job_id}`)
- Human approval of proposed changes (`POST /v1/chat/{session_id}/approve`)
- DOCX export (`POST /v1/documents/export`)

## Limitations / next steps

- The host-page extractors are intentionally narrow and tested against the current ChatGPT and Claude page structures; a production release needs automated browser fixtures and selector maintenance.
- A popup must remain open while a fresh job is polled. The job ID is saved, so reopening the popup resumes its status, but background polling and notifications are not implemented yet.
- This first draft has no recorded demo yet. Add a link here after a real key-backed walkthrough has been recorded.
