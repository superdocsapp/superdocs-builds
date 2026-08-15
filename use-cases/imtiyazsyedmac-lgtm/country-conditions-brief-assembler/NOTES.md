# Notes — assumptions and decisions

Logged as the task doc asks: a noted assumption counts in your favor.

**Claim-element taxonomy.** I used five standard asylum/withholding elements (particular social group, persecution/harm, nexus, state protection, no internal relocation alternative). These are textbook doctrine, not case-specific — the card didn't specify a taxonomy, so I picked the one a real country-conditions brief for this audience would actually need to track, and said so here rather than guessing silently.

**Synthetic country and sources.** The card requires fictional/fabricated test data. I invented a country ("Republic of Salvarion"), four source documents (NGO report, news article, government backgrounder, expert declaration), and one deliberate factual contradiction between sources on whether state protection is actually available — because "surfaces contradicting sources" is unfalsifiable to demonstrate against sources that all agree. I used a fictional country rather than a real one so fabricated report text is never mistakable for a real organization's real claims about a real place.

**Two implementations, on purpose.** The card allows completing this without a backend, and SuperDocs itself doesn't browse the web or run arbitrary extraction logic outside chat. I built two things:

1. A deterministic Python engine (`documents.py` → `extract.py` → `assemble.py` → `contradictions.py` → `dependency.py` → `run.py`) that does the actual extraction, verbatim-quote verification, contradiction detection, and source-removal dependency tracking. This is fully testable and re-runnable — `python3 run.py` reproduces every output file.
2. A real SuperDocs session (`superdocs_demo/`) where I pasted the same four sources into chat and asked SuperDocs' own document AI to build the same brief. It independently reached the same two substantive findings my rule-based engine did: the state-protection contradiction, and the honest "no source addresses internal relocation" gap. That agreement is the actual proof this is buildable on top of SuperDocs, not just alongside it — the deterministic engine is the auditable reference implementation, and the live demo is evidence the product itself can do this today, at least for extraction-and-assembly at this scale.

**Extraction method — honest limitation.** The Python engine's tagger is keyword/regex-based, not a live extraction model — same disclosed limitation as Task 1's `enrich.py`, for the same reason (this cloud build environment can't reach a general LLM API directly). It's disclosed in `claim_elements.py`'s docstring and demonstrated as a real, testable `relevance_score()` ranking, not asserted as equivalent to what SuperDocs' own AI did in the live session.

**"Zero is a fine answer."** None of the four sources address internal relocation. The engine reports 0 excerpts for that element rather than stretching a tangential paragraph to fill it, and the live SuperDocs run independently produced the identical honest gap.

**What I'd build next if this went further.** A citation-integrity check that also verifies page/paragraph numbers survive a source's re-pagination (this fixture never re-paginates, so the current verbatim check doesn't need to handle that); and a live-LLM `tag_paragraph()` swap once `api.superdocs.app` is reachable from wherever this actually runs — the pipeline shape doesn't change, per the note in `claim_elements.py`.
