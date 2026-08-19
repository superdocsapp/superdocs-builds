# Chat to SuperDocs

Created by **Abhinav Choudhary**.

Chat to SuperDocs is a Chrome/Chromium extension for people who are tired of pasting AI answers into documents and repairing the formatting. It puts a small **Add** button to the left of every AI response's first readable block. One click turns that response into structured content in a growing SuperDocs document for the current chat.

It keeps headings, nested lists, tables, code blocks, and maths intact. It does not invent a title, heading, summary, or “polished version” label. On the first answer, it lists templates saved in the user’s SuperDocs account; if none exist, it creates a clean blank document instead. Every later answer in the same conversation inherits the chosen styling.

The extension keeps the SuperDocs workflow out of the user’s way:

1. Adds inline controls to responses on ChatGPT (both current and legacy domains) and Claude, with generic semantic selectors for other Markdown-based AI chat interfaces.
2. On the first click in a conversation, lists the user’s saved SuperDocs templates in an inline picker; it creates a conversation-scoped document from the selected template.
3. On later clicks, appends the selected response to that same document and preserves the established template styling.
4. Sends an async edit request and applies its changes automatically; the only in-progress signal is a revolving outline around the Add button.
5. Keeps the completed HTML per conversation for subsequent additions.

## Why a local bridge?

SuperDocs API keys must remain server-side. This extension never reads, stores, or sends an API key. Instead, a tiny localhost bridge receives extension requests and adds the key from its own environment before calling SuperDocs. The bridge accepts requests only from the specific extension origin you configure.

## Run it

Requirements: Node 18+ and a SuperDocs API key. Saved SuperDocs templates are optional. Do not put the key in this repository or in the extension.

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

3. Optionally, create or upload a branded template in SuperDocs. The extension lists only templates available to the account behind `SUPERDOCS_API_KEY`; when none exist, it uses a blank document.
4. Open a completed ChatGPT or Claude conversation. The extension adds an **Add** button just left of each assistant response.
5. Click **Add** beside the first answer and choose a saved SuperDocs template in the small in-page menu.
6. Later **Add** clicks append to the same conversation document without asking for the template again.

The extension toolbar icon opens settings only; the document workflow itself never uses a popup. The options page deliberately permits only `http://127.0.0.1:8787` in this first draft, avoiding the accidental transfer of document content to an arbitrary endpoint.

The background worker authenticates to the bridge with its extension origin because Chrome service-worker fetches omit the normal `Origin` header. Keep `ALLOWED_EXTENSION_ORIGIN` set to the exact `chrome-extension://…` value (without a trailing slash); the bridge rejects requests that do not carry that matching extension-origin value.

## Test

```sh
npm test
```

The tests are offline and cover rich-structure preservation in the document envelope, conversation-scoped appending, append-mode safeguards, the required double JSON parse of proposed-change events, automatic processing state, and completed-document extraction.

## SuperDocs features used

- Async chat editing (`POST /v1/chat/async`)
- Saved-template listing (`GET /v1/templates`)
- Job polling (`GET /v1/jobs/{job_id}`)
- Automatic change application (`approval_mode: "approve_all"`)

## Limitations / next steps

- The host-page extractors use a common semantic strategy with small ChatGPT/Claude adapters. A production release needs automated browser fixtures and selector maintenance as chat sites change their markup.
- The in-page control polls while its chat tab remains open. The job ID is saved, so reopening the conversation can resume status, but background notifications are not implemented yet.
- This first draft has no recorded demo yet. Add a link here after a real key-backed walkthrough has been recorded.
