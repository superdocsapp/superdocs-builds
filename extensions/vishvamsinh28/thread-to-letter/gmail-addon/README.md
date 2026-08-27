# The Gmail add-on

Reads the open thread, pulls out what people actually committed to, lets you tick the
real ones, and attaches the resulting letter to a draft reply — all inside Gmail.

> **Status: the code runs and is exercised against the live API. Google's own binding
> is not verified.**
>
> Apps Script is ordinary JavaScript against a handful of Google globals, so `Code.gs`
> and `Prompts.gs` can be run outside Google by stubbing them:
>
> ```bash
> make addon        # from the parent folder — 2 operations
> ```
>
> That executes these files **unmodified** against `api.superdocs.app`: it reads a real
> thread, builds the real cards, extracts and verifies commitments, drafts the letter and
> creates the draft reply with the attachment. See `simulate.js`.
>
> What that leaves unproven is only whether Google's runtime renders these cards and
> delivers these events — I could not sideload into a real mailbox during the round.
> Expect to fix small rendering things on first install; the logic is not where it will
> break.

## What it does, screen by screen

**1. Open any thread in Gmail.** The add-on appears in the right-hand sidebar with one
button: *Find commitments*.

**2. Press it.** It reads every message in the thread (`GmailApp`), strips quoted history
and signatures so each message is only what its sender typed, and sends the thread to
SuperDocs with the extraction prompt. **One operation.**

**3. You get a checklist.** Every candidate, labelled:

| | |
|---|---|
| `FIRM` | somebody accepted an obligation — **pre-ticked** |
| `SUPERSEDED` | replaced later in the thread — unticked |
| `HEDGED` | *"we should be able to"*, *"hopefully"* — unticked |
| `SECOND-HAND` | what a third party might do — unticked |
| `PROPOSED` | floated, never agreed — unticked |

Anything whose quote is **not actually in the thread** is marked `UNVERIFIED` and left
unticked. That is the check that stops a confident invention reaching a letter you send.

If a commitment was superseded and its replacement is missing, you get a warning — the
letter would otherwise omit the obligation that actually stands.

**4. Tick what's real, press *Write letter and attach to reply*.** SuperDocs drafts a
formal letter from the ticked commitments **only** (one operation), exports it as `.docx`
(free), and `createDraftReply` puts it in your drafts as a reply to that thread with the
letter attached and a short body listing what it recorded.

**5. You read it and press send.** Nothing is ever sent for you.

**Cost: two operations per thread.** Reading the thread, verifying quotes, exporting and
creating the draft are all free.

## Installing it

A Gmail add-on must be a **standalone** Apps Script project. *Extensions → Apps Script*
inside Docs or Sheets creates a *bound* script, which is a different thing and cannot
carry a Gmail add-on manifest.

### Option A — browser only, no tools

1. Go to **[script.google.com/home/projects/create](https://script.google.com/home/projects/create)**.
2. Rename the project to `Thread to letter`.
3. **Project Settings** (gear) → tick **“Show `appsscript.json` manifest file in editor”**.
4. Back in **Editor**, replace the contents of each file with this folder's:
   - `appsscript.json` → paste over the existing manifest
   - `Code.gs` → paste over the default `Code.gs`
   - `Prompts.gs` → **File → +  → Script**, name it `Prompts`, paste
5. **Project Settings → Script Properties → Add script property**
   - name `SUPERDOCS_API_KEY`, value your `sk_…` key.
   The key lives here, never in the source.
6. **Deploy → Test deployments → Install**, then **Done**.
7. Open Gmail, hard-refresh, open any thread. The add-on is in the right sidebar.

First run asks you to authorise. On a personal `@gmail.com` account you will see an
*"unverified app"* interstitial — **Advanced → Go to Thread to letter (unsafe)**. That is
Google's warning for any add-on you have not published, including your own.

### Option B — from the command line with `clasp`

```bash
npm install -g @google/clasp
clasp login
```

Then from **this folder**:

```bash
clasp create --title "Thread to letter" --type standalone --rootDir .
clasp push -f
clasp open
```

`clasp create` writes a `.clasp.json` here (it is gitignored). `push -f` overwrites the
default files Google created with the ones in this folder. Then in the browser tab
`clasp open` gives you: set the Script Property as in step 5 above, and
**Deploy → Test deployments → Install**.

After any edit:

```bash
clasp push -f      # then hard-refresh Gmail
```

Watching the logs while you use it:

```bash
clasp logs --watch
```

## The scopes it asks for, and why

| Scope | Why |
|---|---|
| `gmail.addons.execute` | run as a Gmail add-on at all |
| `gmail.addons.current.message.readonly` | read the thread you have open |
| `gmail.compose` | create the draft reply. **Compose only — it cannot send** |
| `script.external_request` | call `api.superdocs.app` |

No `gmail.modify`, no `gmail.send`. It can write a draft and nothing else.

## If it misbehaves

| Symptom | Cause |
|---|---|
| *"No SUPERDOCS_API_KEY"* | Script Property not set, or set on the wrong project |
| Sidebar never appears | not installed as a **test deployment**, or Gmail needs a hard refresh |
| `401` from SuperDocs | the property value must be just `sk_…` — no quotes, no `Bearer` |
| Add-on times out | Apps Script caps at 6 minutes; a very long thread may exceed it. Use the Python CLI or console in the parent folder for those |
| Nothing ticked after extraction | every candidate was hedged, second-hand or unverified. That is a real answer — check the quotes |

## The same thing without Gmail

The parent folder runs the identical pipeline with no OAuth at all, and it *is* tested:

```bash
cd ..
make console                                    # browser review console
uv run thread2letter run my-thread.mbox         # or the terminal
```

It produces a `reply-*.eml` you can open in Gmail as a draft reply — same output, no
install.
