# Kitline: In-Game Text Localization Kit

Built by Dheeraj Mishra for the SuperDocs task.

I picked game localization because it is easy to lose important context in a normal string spreadsheet. A line like `REACTOR OVERLOAD: {seconds}s` is not just text. It is a HUD warning, has a short display limit, and contains a variable that cannot be changed. The translator needs that information before they start, not after QA finds a broken build.

Kitline is my attempt at making that handoff less fragile.

![Kitline review desk with source context, returned translations and row-level validation](assets/kitline-review-desk.png)

## What is in the kit

- Source string, string ID, character limit, speaker and scene note
- Game and tone context for the translator
- A do-not-translate list for names, variables, tags and UI tokens
- A small style sheet for the locale
- Returned translation fields with row-level warnings

The warnings catch missing or added tokens, missing protected terms and likely display-width overflow. They are there to make review faster, not to replace a linguist or an in-game QA pass.

## How I use it

1. Pick a sample kit and enter the target language.
2. Fill in the brief and add any protected terms or style rules.
3. Paste the vendor's translations into the right rows.
4. Read the warnings and correct the rows that need attention.
5. Send the generated handoff to SuperDocs.
6. Check each suggested context or style edit, then export the reviewed DOCX.

Changing a template clears the returned translations on purpose. I did not want text from one localization job carrying into another one by accident.

## SuperDocs part

The browser sends the generated kit to a local Express server, not directly to SuperDocs. That server keeps `SUPERDOCS_API_KEY` private, starts an `ask_every_time` review, polls for the result, sends back the producer's decisions, and exports the DOCX.

The review is limited to context and style guidance. The instruction says to leave IDs, source strings, limits, speaker and scene details, protected tokens, and the do-not-translate list alone. The app also keeps the `data-chunk-id` values in the generated HTML so the document can be reviewed consistently.

## Run locally

```bash
npm install
```

Copy `.env.example` to `.env`, add `SUPERDOCS_API_KEY`, then run:

```bash
npm run dev
```

For a build check:

```bash
npm test
npm run build
```

## What I verified

- Six local tests cover token handling, protected terms, display width, search and proposed-change parsing.
- I ran a synthetic kit through the live SuperDocs review flow, approved a change and exported a DOCX successfully.

## Gaps I know about

This version does not import CSV, XLIFF or Google Sheets yet. It also uses a display-width estimate, not the real game font or a device preview. Those would be the next things I would add if this became a tool for an actual localization team.
