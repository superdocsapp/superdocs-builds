# What gets listed

The badge only means something if the list behind it has been checked. These are
the rules, written down in advance so a rejection comes with a reason instead of
silence.

## The three checks

A reviewer applies these in order and stops at the first one that fails.

### 1. There's something to open

A published page, a repository, a file in a release, a public export. Not a
screenshot of one, not a private link, not a description of something that exists
elsewhere.

### 2. SuperDocs did work that mattered

Name the feature you used and what it did — editing inside the document, tracked
changes, export, the API, the MCP server. Then apply the test:

> If you could have produced the same result, at the same risk, by typing into a
> plain text editor, it doesn't qualify.

Most rejections happen here, and that's intended. "I opened my document in
SuperDocs" isn't use. "Section editing let me revise one clause of a contract
without touching the eleven around it, and I can show the others didn't change"
is.

### 3. Someone else can check it

A second link a stranger can open: a commit, a diff, an exported file, a public
write-up, a pull request. "We use it internally" can't be verified, and an
unverifiable entry is worth less than no entry.

## Two conditions

- **You submit your own project.** Nothing gets added by scraping other people's
  work. Being written about without being asked isn't a favour.
- **Both links are safe to publish.** No credentials, no personal data, nothing
  under NDA, and no private individuals named.

## Why entries get rejected

The reviewer records one of these next to the entry, in public.

| Code | Reason |
|---|---|
| **R1** | Not submitted by the person who built it |
| **R2** | Nothing to open — the evidence is a screenshot, a dead link, or private |
| **R3** | SuperDocs was incidental; a plain text editor would have done the same job |
| **R4** | Not real work — a hello-world, or a document made to qualify for the badge |
| **R5** | The project is the badge, the gallery, or exists to be listed |
| **R6** | Unsafe to publish — credentials, personal data, NDA material, or a named private individual |
| **R7** | Claims something about SuperDocs that isn't true |
| **R8** | Couldn't be verified within the review window |

R7 and R8 just need fixing and resubmitting. So does anything else — the checks
are about evidence, not about whether the project is impressive.

## How review works

1. You open an issue or a pull request. See [SUBMITTING.md](SUBMITTING.md).
2. Automated checks run first. They confirm the entry has an evidence link, a
   date, and a decision with a reason. They don't judge the project.
3. A person opens both links and applies the three checks in order.
4. The decision goes into `gallery/manifest.json` — listed or declined — with a
   short reason, and is merged either way. Rejections are recorded, not closed
   quietly.
5. This takes up to seven days. Past that it's declined as R8, which means "send
   it again once the evidence is public".
6. Listed entries get re-checked. If a link dies, the entry comes off the page
   and the reason stays visible.

## Conflicts of interest

The gallery has one entry at the moment and it's my own project. That's marked on
the entry itself. Anything I submit gets the same three checks as anything else,
and the conflict gets noted each time.

This repository isn't in the gallery either. It's the gallery, and listing
yourself to make the list look busier is the thing these rules exist to prevent.

SuperDocs was used on this document — the section above was drafted through the
API and exported — but both sentences it produced were rejected on review, and
the one that shipped was written by hand.

## What this isn't

It isn't a quality bar. Nobody is judging whether the project is good, whether
the code is clean, or whether the idea is clever. There's one question: did
SuperDocs do real work here, and can someone else check that it did?

A rough project with an honest diff gets listed. A polished one with a claim
nobody can verify doesn't.
