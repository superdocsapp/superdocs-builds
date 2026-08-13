# SuperDocs Review for Zoho Writer

A narrow Zoho Writer right-sidebar extension for reviewing AI edits to the current selection. It uploads selected HTML, starts an asynchronous `ask_every_time` chat, polls the durable job, handles item-level mixed approval and continue prompts, and exports the approved SuperDocs session.

**Screenshot evidence:** TODO — capture only after the extension is run in a real Sigma/Writer account.

**Demo evidence:** TODO — record only after the live workflow and host behavior are verified.

## Current capability

- Persistent `writer.extensions` sidebar with visible Read → Upload → Process → Review → Finish stages.
- Secure SuperDocs calls through `SigmaSDK.WRITER.request` and the named `superdocsapi` connection.
- Item-level accept/reject cards, repeated approval rounds, and `metadata.awaiting_kind=continue_prompt`.
- Stage-aware retry and reload recovery: once a job ID exists, the extension stores only the opaque session/job IDs plus gate status and resumes that job without another upload/chat.
- Usage, progress, errors, DOCX export, and separately tested polling/SSE normalization.

Automatic Writer writeback is deliberately unavailable. The current Sigma SDK v3 documentation describes `insertContent` at the cursor; it does not establish selection replacement, a stable range API, or a Track Changes control. SuperDocs parsed structural HTML is therefore review data only and is never substring-mapped onto Zoho HTML. Apply reviewed wording manually in Writer, or use the approved export.

## Exact setup

Prerequisites: Node.js `>=20.19 <21` or `>=22.12` (matching `package.json` and the locked Vite/jsdom toolchain), npm, a Zoho Sigma workspace with a Writer extension, and a SuperDocs API key.

1. Install and verify:

   ```bash
   npm install
   npm test
   npm run package:sigma
   ```

   The default command creates `release/zoho-writer-superdocs-source.zip`. This is a **source import bundle, not a directly installable configured extension**. For Sigma's ZIP importer, it places `plugin-manifest.json` at archive root and widget assets under `app/dist/`. It intentionally has no connector.

2. In Zoho Sigma, create or open a **Zoho Writer** extension.
3. In Sigma **Connections**, create a custom service named `superdocs`:
   - Base URL/domain: `https://api.superdocs.app`
   - Authentication type: API key
   - Request header: `Authorization`
   - Value format: `Bearer <key>`
   - Connection link name: `superdocsapi`
   - Use login-user credentials when each installed user supplies their own key.
4. Keep Sigma's generated connector configuration and credentials outside this repository:
   - export the target workspace's complete `connectors` array;
   - save `{ "connectors": [...] }` as ignored `config/connector.workspace.json`;
   - verify it contains `connectionLinkName: "superdocsapi"` and no API key/token fields.
5. Build a workspace-specific bundle:

   ```bash
   npm run package:sigma:workspace
   ```

   This creates `release/zoho-writer-superdocs-workspace.zip`. The packager merges the ignored overlay into the packaged manifest in memory, does not copy the overlay file, rejects credential-looking fields/values, and validates every manifest target.
6. Import the workspace bundle into Sigma. The packaged manifest is at archive root and points to `app/dist/index.html` plus assets under `app/dist/img/`.
7. Confirm `https://api.superdocs.app` remains in `whiteListedDomains`, authorize the connection in Sigma, and run the extension.
8. Open a Writer document, select a passage, and open **SuperDocs Review** in the right sidebar.

The browser extension does not read `.env`. `.env.example` exists only for the opt-in Node live smoke test.

## Architecture

```text
Writer SelectedContent (HTML snapshot)
          │
          ▼
SigmaSDK.WRITER.request + superdocsapi
          │
          ├─ POST /v1/documents/upload
          ├─ POST /v1/chat/async (approval_mode: ask_every_time)
          ├─ GET  /v1/jobs/{id}
          ├─ POST /v1/chat/{session}/approve
          ├─ POST /v1/chat/{session}/continue
          └─ POST /v1/documents/export
                         │
                         ▼
              approved DOCX download

Writer host document: never mutated by this build
```

- `src/api.ts`: exact request contracts, URL encoding, named-connection transport, upload, approve, continue, polling, and export.
- `src/normalizers.ts`: polling wrappers, encoded pending changes, operation allow-listing, continue prompts, usage, and separately framed/double-encoded SSE data.
- `src/workflow.ts`: durable active session/job context, approval and continue gates, resumable polling, and explicit host-writeback block policy.
- `src/state.ts`: validated browser persistence containing only session ID, job ID, active status, and optional awaiting kind.
- `src/view.ts`: proposal cards built with DOM APIs and `textContent`; no external field is interpolated into HTML.
- `scripts/package.mjs`: creates and validates distinct source/workspace Sigma bundles in the documented layout.

## Safety and limitations

- No API key or token is stored in source or package output. Generated connector metadata appears only in the workspace bundle created from the ignored local overlay; it is absent from Git and the default source bundle.
- Browser storage never contains selected HTML, instructions, proposals, exports, or credentials. Invalid/terminal state is cleared.
- Only the current selected HTML is uploaded.
- Proposed `old_html`/`new_html` is displayed as untrusted review data. It is not mapped against Writer HTML.
- Unknown operation names are normalized to `unknown` and rendered as text.
- `create`, `delete`, and `insert_after_chunk_id` proposals explicitly require a future verified chunk/range host API; they have no Writer writeback path.
- The project has no experimental writeback flag. Adding one requires live Sigma evidence of exact selection replacement plus a fresh exact-selection guard; `insertContent` alone is insufficient.
- A failure before SuperDocs returns a job ID cannot be resumed safely. The UI says that starting again is a separate new run. Once an ID exists, retry and reload recovery preserve that job and do not create another billable request.
- No Zoho or SuperDocs account credentials were available during repository verification, so live host behavior and authenticated API transport remain TODO evidence.
- The exact credential-gated verification procedure and implementation gate are in [`docs/live-sigma-spike.md`](docs/live-sigma-spike.md).

## Tests

Offline tests require no key:

```bash
npm test
```

Coverage includes polling and separately double-encoded SSE normalization, operation validation, malicious rendering values, named-connection request shapes, encoded malicious path values, mixed approval with required top-level `approved`, repeated rounds, continue prompts, same-job retry/reload recovery without another upload/chat, safe persisted-state shape, and explicit structural-writeback blocking. Both packaging modes separately validate every manifest-referenced `app/` target and reject environment files or credential-looking manifest content.

Run the credential-gated, non-billable authentication smoke test explicitly:

```bash
SUPERDOCS_API_KEY=your-key-here npm run test:live
```

Without the variable, that test is skipped.

## Credit

I built this for the SuperDocs task.
