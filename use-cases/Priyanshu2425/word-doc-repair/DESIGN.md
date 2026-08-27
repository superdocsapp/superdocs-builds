# Design — Salvage

The web page for this build, and only this build. It shares no visual language
with anything else its author has built, deliberately: a person whose file just
broke is not the same person, on the same day, as somebody reviewing a document
at their desk.

## The world

A postal recovery notice — what an institution sends you when your item arrived
damaged. A printed wrapper, chevron edge tape, a docket number, a rubber-stamped
verdict, and language that takes responsibility in plain words.

It was chosen because it carries the product's truth exactly: careful custody of
something that is not ours, an honest account of what survived, and bad news
delivered in the same voice as good news. It is not the SaaS uploader page — no
hero, no feature cards, no dashed rectangle — and it is not a terminal.

## Colour

Committed: the institution's blue owns the marks and the actions, red belongs to
damage, and the ground is a cool form stock so the page never reads as warm
stationery.

| Token | Light | Meaning |
|---|---|---|
| `--stock` / `--sheet` | `#e9ebe6` / `#fcfcfa` | the desk, the notice |
| `--ink` / `--ink-2` / `--ink-3` | `#14171a` / `#494f55` / `#7b8188` | text, secondary, tertiary |
| `--post-blue` | `#173f8a` | the institution: marks, stamps, the download action |
| `--post-red` | `#c2222c` | damage: the failed stamp, losses, refusals |
| `--kept` | `#16603c` | one tick, beside something that survived |

Red is never used for emphasis or decoration — only for something that was lost
or refused. Dark mode is the same notice under a desk lamp.

## Type

The system UI stack, set large: 17px body, 28–38px headline, short measure. One
monospace, used only for the record line — filename, size, docket — because that
is a form field, not a costume.

## Devices with a fixed meaning

- **Chevron tape** — edges anything in our custody: the notice itself, and the
  panel holding the repaired file. Nothing else.
- **The stamp** — one verdict, landing once with a small rotation: *Recovered*,
  *Recovered in part*, or *Could not be repaired*.
- **Stations** — the engine's real stages, shown while it works, then folded
  behind a disclosure once the verdict is known. The answer outranks the working.
- **The record line** — file, size, docket. A receipt, so the page has a name for
  the thing it is holding.
- **The styling line** — one sentence inside the handover panel saying whether
  the file being handed over went through the styling pass, and on success
  linking the unstyled copy beside it. It is a line and not a panel because
  styling is no longer a second thing to decide about: it happens inside the
  recovery, so there is nothing to offer here and only something to report. The
  block that used to ask — *"A styled copy, if you want one"* and its button —
  was removed on 2026-08-26 along with the capabilities probe that decided
  whether to draw it.
- **The sheet** — the rebuilt document itself, pictures inline, rendered for
  reading, between the losses and the handover. It carries no chevron tape: tape means *in our
  custody* and edges only the notice and the panel holding the file, and this is
  the contents rather than the custody. It sits above the download because the
  question it answers is asked before the download, not after.

## Rules that are not style

- A failure renders no "what came through" section and no download. (BUG-012.)
- Losses are set at the same weight as recoveries. Styling losses as a footnote
  would be the overclaim this build refuses, expressed in CSS.
- Retention is stated where the file is handed over, before it can expire.
- A step this copy of the page cannot take is never rendered as a button. Since
  the styling pass runs inside the recovery, there is no longer a button to
  withhold — what remains is the obligation to say which of the two files the
  person is being handed, and why, in one sentence.
- **The styled file is what is handed over, and the plain rebuild is always
  still reachable.** These are one rule, not two. The brief for this build
  defines a strong result as a valid, *styled* file, so the styled copy is the
  promise rather than the extra — but a person who wants the unstyled rebuild
  gets a link to it rather than a second run.
- A degraded styling pass is stated, never silent. No key, an exhausted
  allowance, a timeout, or a styled file refused by the content guard each get
  their own sentence in the place the download is offered. A page that quietly
  hands over the fallback is making the claim this build refuses to make.
- The verdict is a claim and the sheet is the thing itself. Where both are on
  screen the sheet is never smaller than the claim about it.
- No engine vocabulary reaches the page — not in a stage line, not in a list, not
  in an error. Enforced over rendered output, for every fixture. (BUG-014, BUG-020.)
- No sentence claims a complete, perfect or guaranteed repair. Also enforced over
  rendered output, with negations understood: *"not a complete repair"* is the
  sentence this product exists to say.

## The counter

A second screen, reached from one line inside the handover panel and from
nowhere else. The document on the left, a line to SuperDocs on the right; on a
phone the document holds the screen and the counter is a drawer. Chosen shape is
V5 in `docs/style-it-yourself/`; the logic is `docs/PRD-SET-IT-YOUR-WAY.md`.

- **The rail is quiet.** No transcript. One field, one sentence back, and
  receipts — one ruled line per instruction, newest first, the way a statement
  lists what has happened to an account. The full exchange sits behind a
  disclosure. This is the same rule the stations already follow: the answer
  outranks the working, and the answer to *make the headings smaller* is smaller
  headings, not a paragraph claiming they are smaller.
- **The before-and-after toggle** is what the saved width buys. Four changes in,
  *what did I actually change?* is the real question, and no amount of chat
  answers it as well as showing the file both ways.
- **A word the person typed is marked as theirs.** The model never writes prose
  into a recovered document, and where the person has put their own words in, the
  handover says how many. Provenance is the whole product: these are supposed to
  be *your* words.
- **Two kinds of no, and the page distinguishes them.** A refusal made before
  anything is sent costs nothing and says so. One made on a file that came back
  wrong was already charged for, and saying "nothing was counted" there would be
  the small lie this build does not tell.
- **No tape on the counter.** One strip at the top of the shell, as everywhere
  else. Tape means *in our custody*; the sheet is the contents, not the custody.
- **Red stays red.** A refusal takes the red mark, because a refusal is a loss of
  something asked for. An applied change takes post-blue, because it is not.

## Removed, and why

- **The sheet's heading and its note.** *"What is in the file"* and *"Read it
  here before you download it. This is the rebuilt document itself, not a
  description of it."* The sentence was true and was the right rule, but it was
  explaining something that explains itself — a person looking at their own
  document does not need to be told it is their own document — and the heading
  took the eye before the page's actual answer did. The sheet is unchanged and
  still sits between the losses and the handover; only the label above it is
  gone. The section keeps an accessible name for anyone reading by ear, where
  nothing else supplies one, and the rule is now enforced against the sheet's
  contents rather than against a sentence about them.

- **The asides panel.** *"Recovered asides"* reprinted the footnotes, headers and
  footers on the page. They were already written into the rebuilt document
  behind its `--- RECOVERED ASIDES ---` marker, which is where they belong, so
  the panel made the report a second copy of the document instead of a summary
  of it. The recovery is unchanged; only the echo is gone.

## Mobile

Designed at 400px first. One column throughout, controls at full width, the
verdict and the download reachable without a horizontal thought.
