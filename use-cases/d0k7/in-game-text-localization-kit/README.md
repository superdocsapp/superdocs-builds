# Kitline: In-Game Text Localization Kit

Built by Dheeraj Mishra for the SuperDocs task.

I built Kitline around a small but annoying game-localization problem: a translator often receives isolated strings in a spreadsheet and has to guess what they mean, who is speaking, where the text appears, and how much space is available.

Kitline turns that string table into a handoff document. It keeps the English source beside the returned translation, adds world and scene context, records character limits, and keeps protected game terms visible. Before the handoff is exported, it checks each row for missing tokens, changed tags and obvious width risk.

The sample data is fictional. I used a combat warning, a named character and an objective tag because they show the kinds of strings that can break when localization is treated as simple text replacement.

![Kitline review desk with source context, returned translations and row-level validation](assets/kitline-review-desk.png)

## How I expect someone to use it

1. Pick one of the sample handoff templates and set the target language.
2. Add the game context and voice notes that a translator needs.
3. Paste the translations returned by the vendor into the matching rows.
4. Fix or consciously accept any warnings about tokens, protected terms or display width.
5. Send the handoff document to SuperDocs for a review of the context and style notes.
6. Approve or reject each proposed edit, then export the reviewed document as DOCX.

The app does not translate the strings itself and it does not auto-approve edits. Those are producer decisions.

## Why the local checks exist

I did not want an editing model to silently change a game variable such as `{playerName}`, an inventory tag such as `[ITEM_VANTA_CORE]`, or markup such as `<c=warning>`. Kitline compares the source and returned text locally first. It also uses a simple display-width estimate so a producer can see strings that are likely to be too wide for a UI.

The width check is only a warning. It cannot replace testing a real game font on a real screen.

## Where SuperDocs fits

Kitline generates HTML with stable `data-chunk-id` values and sends it to SuperDocs through a small local Express server. The server starts an async review using `ask_every_time`, polls for the result, shows each proposed change in the UI, submits the decisions, and exports the final DOCX.

I use SuperDocs only for a narrow review of the translator context and style guidance. The review instruction tells it to preserve string IDs, English source text, limits, speaker and scene fields, protected tokens and the do-not-translate list. The API key stays on the server and never reaches the browser.

## Run it locally

```bash
npm install
```

Copy `.env.example` to `.env` and put your `SUPERDOCS_API_KEY` there. Then run:

```bash
npm run dev
```

Open the address printed in the terminal. For a production build:

```bash
npm run build
npm run serve
```

## Checks I ran

`npm test` covers protected formatting tokens, repeated protected terms, proper nouns, target-script width, string-table search and parsing both normal and double-encoded proposed-change payloads.

I also ran a synthetic kit through the live SuperDocs flow: async review, an explicit approval and a DOCX export all returned successfully. No API key or source document is committed to this repository.

## What I would build next

For a real team, I would add CSV, XLIFF and Google Sheets imports, per-locale terminology rules and a real rendering check using the target game font. This version is intentionally a focused working slice, not a complete translation-management system.
