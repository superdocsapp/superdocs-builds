# Running this project on your own machine

Hey — if you found this repo and want to actually run it yourself instead of just
reading the code, this is everything I did to get it working locally, in order.
I'm writing this the way I'd explain it to a teammate sitting next to me, not as a
generated checklist, so read it top to bottom and you'll be up and running in about
15 minutes.

A quick note before we start: this is a CLI tool, not a website. It talks to
[SuperDocs](https://superdocs.app) (a real product with a real API) to draft
Win/Loss debriefs from sales call transcripts, and then rolls a quarter's worth of
those debriefs up into one shared competitive brief. Everything runs from your
terminal.

## What you'll need first

- Python 3.10 or newer on your machine
- A free SuperDocs account (you'll make one in a couple of minutes, no card needed)
- About 15 minutes and a terminal you're comfortable in

I did all of this myself on Windows using Git Bash, so I'll give you the commands
for that, plus a note wherever PowerShell or Mac/Linux users need something
slightly different.

## 1. Get the code onto your machine

If you grabbed the zip from this repo's releases or downloads, just extract it
somewhere sensible:

```bash
unzip superdocs-winloss.zip
cd superdocs-winloss
```

If you'd rather clone it with git, that works too — same result either way.

## 2. Set up a virtual environment

I always keep this project's dependencies isolated in a venv rather than installing
into my system Python, and you should too — it avoids any conflicts with other
projects on your machine.

```bash
python -m venv .venv
source .venv/Scripts/activate    # Git Bash on Windows
```

If you're on plain Windows PowerShell instead of Git Bash, use
`.venv\Scripts\Activate.ps1`. On Mac or Linux, it's `source .venv/bin/activate`.

Once it's activated you'll see `(.venv)` show up at the start of your prompt. That's
how you know it worked.

## 3. Install everything

```bash
pip install --upgrade pip
pip install -e .
pip install pytest responses
```

The `-e .` installs the project itself in "editable" mode, which also gives you the
`winloss` command on your PATH. The last line pulls in what you need to actually run
the test suite.

## 4. Make sure it all works before touching the real API

This project ships with a full test suite that runs against mocked responses, so
you don't need a SuperDocs account or any credentials at all to check that the code
itself is sound:

```bash
pytest tests/unit -v
```

You should see everything pass. If something fails here, stop and figure that out
first — everything after this step assumes this baseline is green. In my case this
has consistently passed clean, so if you hit a failure it's almost always a Python
version mismatch or the venv not being activated.

## 5. Try the CLI without any credentials at all

Every command that would normally talk to SuperDocs supports a `--dry-run` flag,
which prints out exactly what it *would* send, with zero network calls. It's a
good way to get a feel for what the tool does before you commit to setting up a
real account:

```bash
winloss debrief create \
  --transcript data/transcripts/2025q4_nimbus_freight_win.txt \
  --deal-code DEAL-2025Q4-001 \
  --quarter 2025Q4 \
  --segment Mid-Market \
  --outcome win \
  --customer-name "Nimbus Freight Systems" \
  --dry-run
```

That'll dump a JSON block showing the session it would open and the exact
instruction it would send to SuperDocs. No key, no internet call, nothing spent.

## 6. Get yourself a real SuperDocs API key

Now for the real thing. Go to **use.superdocs.app** and sign up — it's free, no
card required, and you get a decent monthly allowance of operations to play with.

Before you do anything else in the product, upload some random document and ask it
to make a small edit through the chat, just to see how the actual editor works.
Honestly do this — the CLI is built on top of the same API the web app uses, and
it's much easier to understand what's happening once you've seen it work manually
first.

One thing worth knowing going in: the very first message you send in a brand new
session can be a bit slow, or occasionally time out while things spin up on their
end. If that happens, just send it again — it settles down after that. This isn't
a bug in this project, it's just how a fresh session behaves.

Once you're comfortable with the product, go to your account settings (the gear
icon) → API Keys → Create API Key. Copy it somewhere safe — it's only shown once,
and it starts with `sk_`.

## 7. Load your key into the terminal

```bash
export SUPERDOCS_API_KEY="sk_your_real_key_here"
```

On PowerShell that's `$env:SUPERDOCS_API_KEY = "sk_your_real_key_here"` instead.

This only lasts for your current terminal session — if you close the window you'll
need to set it again, or copy `.env.example` to `.env`, fill in the real key there,
and load it from that file instead if you'd rather not retype it every time.

Quick sanity check that the key actually works, without spending anything:

```bash
curl https://api.superdocs.app/v1/sessions \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY"
```

If that comes back with a JSON response instead of an error, you're good to go.

## 8. Run the real integration test

This one actually talks to the live API and spends a small number of real
operations — nothing to worry about, it's one tiny transcript.

```bash
pytest tests/integration -m integration -v
```

This is deliberately kept separate from the mocked test suite in step 4, so you
always know which kind of test you're running. One makes network calls and costs
you something, the other doesn't.

## 9. Now actually use the thing

This is the real workflow. Each of these commands creates a debrief from a sales
call transcript — there are a handful of sample transcripts already included under
`data/transcripts/` so you don't need to write your own to try this out.

```bash
winloss debrief create \
  --transcript data/transcripts/2025q4_nimbus_freight_win.txt \
  --deal-code DEAL-2025Q4-001 \
  --quarter 2025Q4 \
  --segment Mid-Market \
  --outcome win \
  --customer-name "Nimbus Freight Systems" \
  --auto-approve
```

The `--auto-approve` flag skips the interactive review step and just accepts
whatever SuperDocs proposes, which is handy for running through a batch of these
quickly. If you leave it off, you'll actually get prompted to approve or reject
each change it wants to make — more on that below.

Go ahead and run that same command for the other sample transcripts too, swapping
in different deal codes, segments, and outcomes — there are four or five of them in
the `data/transcripts` folder covering different scenarios (wins, losses, small
sample competitors, one with no competitor mentioned at all).

Once you've got a few debriefs created, you can list what's been indexed locally:

```bash
winloss debrief list --quarter 2025Q4
```

or search across everything you've created by competitor:

```bash
winloss search --competitor "Comp Corp"
```

And then the part that ties it all together — rolling everything from a quarter
into one shared competitive brief:

```bash
winloss brief quarterly --quarter 2025Q4 --auto-approve
```

This one's doing more than it looks like: it pulls in every debrief from that
quarter, works out win/loss patterns per competitor and per segment on its own
(not by asking the AI to count, deliberately — those numbers are computed locally
and just handed to the model as facts to write around), flags anything based on
too small a sample to draw real conclusions from, and makes sure no actual
customer name ends up in the final shared document. That last part isn't just a
prompt asking nicely — there's an independent check afterward that scans the
finished document and refuses to save it if it finds a real customer name in
there.

You can run that same check yourself on any exported file:

```bash
winloss redact-check outputs/briefs/2025Q4.docx
```

## 10. Try the actual review flow

If you want to see the human-in-the-loop review working (not just auto-approving
everything), drop the `--auto-approve` flag:

```bash
winloss debrief create \
  --transcript data/transcripts/2026q1_blue_anchor_win.txt \
  --deal-code DEAL-2026Q1-001 \
  --quarter 2026Q1 \
  --segment Mid-Market \
  --outcome win \
  --customer-name "Blue Anchor Logistics"
```

You should get prompted to approve, reject, or reject-with-feedback for whatever
changes it's proposing. Worth trying a deny-with-feedback at least once just to see
it revise based on what you told it.

## 11. Go look at what got created

Everything ends up in the `outputs` folder:

```bash
outputs/debriefs/DEAL-2025Q4-001.docx
outputs/briefs/2025Q4.docx
outputs/briefs/2025Q4.pdf
```

Open any of them up in Word or whatever you've got — they're normal `.docx` and
`.pdf` files. Worth specifically opening the quarterly brief and checking there's
genuinely no customer name anywhere in it, just deal codes like
`DEAL-2025Q4-001`.

## A few things I ran into myself, worth knowing upfront

**If you're on Windows and something's not being found on PATH after activating
the venv** — double check you actually see `(.venv)` at the start of your prompt.
If you don't, the activation didn't take, and none of the commands after that will
work right.

**If a debrief command already ran once for the same deal code** — running it
again will just tell you it's already indexed and skip, rather than spending
another operation regenerating something that hasn't changed. If you genuinely
want to redo it (say, you edited the transcript, or you're testing something), add
`--force`.

**Operations aren't unlimited** — the free tier gives you a solid monthly
allowance, but if you're going to loop through a lot of transcripts or re-run
things repeatedly while testing, keep an eye on it. Exports themselves don't cost
anything, only the actual chat/drafting calls do.

## If you want to understand how this is actually built

This README covers running it, not how it works internally. For that, this repo
also has:

- `architecture.md` — the actual design: how the pieces fit together, why certain
  decisions were made the way they were
- `task.md` — how the build was broken down into pieces
- `progress.md` — a running log of what was built, what broke along the way against
  the real API, and how each thing got fixed

Worth a read if you're curious, especially `progress.md` — a couple of real bugs
only showed up once this was actually pointed at the live API instead of just
mocked tests, and that file has the full story of tracking those down.

That's it — that's genuinely everything I did to get this running end to end on my
own machine. If something in here doesn't match what you're seeing, it's probably
worth checking your Python version and that your API key actually made it into the
environment variable before anything else.