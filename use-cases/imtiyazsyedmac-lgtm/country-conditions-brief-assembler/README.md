# Country-Conditions Evidence Brief Assembler

Built for the SuperDocs Round 2 hiring task (Task 2 -- assigned build).

**Who it serves:** an asylum or humanitarian-protection attorney assembling the country-conditions record for a filing.

## What it does, in plain language

You give it a set of reports, articles, and expert statements (the kind of evidence that goes into a country-conditions section) and a taxonomy of the claim elements the brief needs to cover. It reads every paragraph of every source, decides which paragraphs bear on which claim element, and produces:

- **A brief**: one section per claim element, each backed by a verbatim quoted excerpt and a full citation (source plus paragraph number). If no source addresses an element, it says so instead of inventing support.

- **An indexed source packet**: every source's full text, paragraph-numbered, so every citation in the brief traces back to an exact passage.

- **A contradiction report**: when two sources disagree about the same claim element (here: whether state protection is actually available), both are surfaced side by side. Neither is dropped in favor of the other.

- **A removal test**: pick any source and see exactly which propositions in the brief lose support, down to which specific excerpts are lost and whether the proposition becomes fully unsupported.

All source material in this build is fabricated test data: a fictional country ("Republic of Salvarion"), fictional organizations, and a fictional declarant. Nothing here is about a real person, case, or country.

## How to run it

No dependencies beyond the Python 3 standard library.

```
cd assigned-build
python3 run.py
```

This ingests the four files in sources/, runs the full pipeline, and writes output/brief.md, output/source_packet.md, output/contradictions.md, and output/removal_test.md. Each module (documents.py, claim_elements.py, extract.py, assemble.py, contradictions.py, dependency.py) is also independently runnable for inspection, e.g. python3 extract.py to see every paragraph-to-element tag before assembly picks the best excerpt per source.

## What SuperDocs features it uses

- **Chat editing**: superdocs_demo/ documents a real SuperDocs session where the four source documents were pasted into chat with instructions to build the same brief this Python engine builds. SuperDocs' own document AI produced a five-section brief with verbatim quotes and citations, and -- unprompted with the specific contradiction -- independently surfaced the same state-protection conflict between sources and reported the same honest "no source addresses internal relocation" gap as the deterministic engine below. That agreement between the two implementations is the actual evidence this is buildable on the product today.

- **Export**: the resulting document was exported from SuperDocs via the in-app Download (Word) action.

- **REST API / MCP**: not used for this build; the card explicitly says neither is required, and this build needed neither a backend nor live document API calls to demonstrate the assembler logic.

See NOTES.md for the full reasoning behind these choices, the taxonomy used, and the honest limitations of the rule-based extraction engine.

## Demo

Screenshot of the live SuperDocs session: superdocs_demo/screenshot_brief.jpg

---

I built this for the SuperDocs Round 2 hiring task.
