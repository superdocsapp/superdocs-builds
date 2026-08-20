# House Style — Product Documentation

The rules a technical writer on this team is expected to follow. This file is the
linter's entire ruleset: it is uploaded to SuperDocs as an attachment, and nothing in
the linter's code knows any of these rules. Editing this file changes what the linter
finds. Replacing it with a different guide changes the linter's behaviour completely,
with no code change.

Each rule has an ID. Findings must cite it.

## Voice and person

- **`active-voice`** — Write in the active voice. "The service validates the token",
  not "the token is validated by the service".
- **`second-person`** — Address the reader as "you". Not "the user", not "one".
- **`no-we`** — Do not write "we" in reference documentation. The product acts, or
  the reader acts.

## Word choice

- **`plain-verbs`** — Prefer the short verb. Use *use* not *utilize*, *start* not
  *initiate*, *end* not *terminate*, *show* not *display to the user*, *let* not
  *enable ... to*.
- **`no-filler`** — Delete filler. Remove *in order to* (use *to*), *at this point in
  time* (use *now*), *it should be noted that* (delete entirely), *basically*,
  *simply*, *just*, *obviously*.
- **`no-please`** — Never write *please* in an instruction. "Run the migration", not
  "Please run the migration".
- **`ui-verbs`** — The reader **selects** an interface element. Not *click*, not
  *tap*, not *hit* — one verb covers every input device.

## Sentences and structure

- **`one-instruction-per-step`** — A numbered step contains exactly one action.
- **`sentence-case-headings`** — Headings are sentence case. "Configure the webhook",
  not "Configure The Webhook".
- **`no-terminal-colon-heading`** — Headings do not end in a colon or a full stop.

## Punctuation

- **`serial-comma`** — Use the serial comma: "tokens, sessions, and webhooks".
- **`contractions-ok`** — Contractions are welcome. *don't*, *you'll*, *it's* all
  read better than the expanded forms.

## Rules that may change a heading

`heading_rules: sentence-case-headings, no-terminal-colon-heading`

Headings are protected by default. Only the rules named on the line above are allowed
to rewrite one; every other rule is refused if its fix lands in a heading. This line
lives in the guide, not in the code, so a guide that governs headings differently
changes the behaviour without a code edit.

## What the linter must never touch

These are not style rules. They are the boundary of the linter's authority, and the
guard in `stylefix/guard.py` enforces them without consulting any model.

- Code samples, whether fenced, `<pre>` or inline `<code>`. A code sample that reads
  badly is still correct code, and rewriting it breaks the reader's copy-paste.
- Table cells. Tables are dense by design and the rules above assume prose.
- Headings that already comply.
- Quoted material from another source, including error messages.

## Rule triggers

Machine-readable, so a finding can name the rule it breaks and the batch profile can
rank which guidance is ignored most. Declared here rather than in code: a different
guide declares different triggers and the profile changes with no code edit.

- `plain-verbs: utilize, utilizes, utilizing, initiate, initiates, terminate, terminates, display to the user`
- `no-filler: in order to, at this point in time, it should be noted that, basically, simply, just, obviously`
- `no-please: please`
- `ui-verbs: click, clicks, tap, taps, hit`
- `no-we: we, our`
- `second-person: the user, one should`

Heading case cannot be expressed as a word list; a change that alters only
capitalisation is attributed to the first rule on the `heading_rules:` line.
