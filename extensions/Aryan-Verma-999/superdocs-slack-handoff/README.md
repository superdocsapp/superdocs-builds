# SuperDocs Slack Handoff

SuperDocs Slack Handoff turns a Slack file into a human-gated SuperDocs document workflow. It is a Slack intake and approval surface, not an editor: the document is uploaded to SuperDocs, SuperDocs proposes changes, the requester approves or rejects in Slack, and the provider-exported PDF returns to the original thread.

## What actually happens

1. A user chooses **Send file to SuperDocs** from the message actions menu on a Slack message containing exactly one file.
2. The app opens a modal for a concrete editing/review instruction.
3. The HTTP service verifies Slack's signed request, writes an ID-only handoff record, and immediately acknowledges Slack.
4. The worker gets the current private Slack file URL through `files.info`, downloads the bytes in memory, and uses the live SuperDocs upload → process → async-chat workflow with `approval_mode: "ask_every_time"`.
5. Slack shows one provider proposal. Only the initiating user may approve or reject it.
6. The worker re-fetches the proposal, submits the exact decision to SuperDocs, and, after provider completion, uploads the provider-exported PDF to the source thread.

The database never stores source bytes, document text, proposal text, Slack tokens, signing secrets, or the SuperDocs key. It stores only Slack and provider IDs, names, MIME type, status, and a coarse error class.

## Run locally

First create a blank Slack app at [api.slack.com/apps](https://api.slack.com/apps) with **Create New App → From scratch**. In **Basic Information → App Credentials**, copy the **Signing Secret**. Add it to a local `.env` (never commit it), together with your SuperDocs key:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
set -a; source .env; set +a
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8788
```

In a second terminal, start the worker with the same environment:

```bash
set -a; source .env; set +a
.venv/bin/python worker.py
```

For local Slack testing, expose only the HTTP service with an HTTPS tunnel:

```bash
ngrok http 8788
```

Generate a manifest using that exact ngrok URL, then open the blank Slack app's **App Manifest** page and replace its YAML with the generated file. This is safe now: the running server can verify Slack's callback probes using the signing secret.

```bash
chmod +x scripts/prepare-slack-manifest.sh
./scripts/prepare-slack-manifest.sh https://your-tunnel.ngrok.app
```

Save the manifest, then go to **OAuth & Permissions → Install to Workspace**. Copy the generated Bot User OAuth Token into `SLACK_BOT_TOKEN` in `.env`, restart the HTTP server, and start the worker. The worker stays private on your machine. If the free ngrok URL changes, regenerate the manifest and reinstall the app.

## Required Slack configuration

The included manifest asks only for:

- `commands` for `/superdocs` help;
- `files:read` to retrieve the one file chosen by the user;
- `chat:write` to update the source thread;
- `files:write` to return SuperDocs' exported PDF.

Enable interactivity and the message shortcut from the manifest. The app only works where the bot can post to the originating conversation.

## Offline verification

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py worker.py
```

The unit tests cover Slack request-signature validation, nested JSON proposal parsing, and the rule that the server fetches only private `files.slack.com` download URLs. Live validation requires a Slack app, HTTPS callback URL, SuperDocs key, and a non-sensitive test file.

## Honest boundaries

- This app supports one Slack-uploaded file per handoff. It deliberately does not fetch arbitrary URLs, scrape messages, or retain document content.
- A user must explicitly refresh, approve/reject, and export. No provider proposal is silently applied.
- The current documented SuperDocs REST workflow exposes upload, async chat, approval, polling, and export. It does not expose a provider-hosted editor URL, so this app never claims to deep-link to one.
- The worker is a single durable SQLite queue suitable for a self-hosted deployment. For a multi-instance production deployment, replace the queue with Postgres plus a separately supervised worker process.
