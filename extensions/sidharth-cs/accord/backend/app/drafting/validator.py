"""Deterministic pending-change validator — the HITL gate.

SuperDocs proposes changes (operation, chunk_id, old_html, new_html,
ai_explanation); OUR CODE decides whether the proposal is acceptable before
approving it. Nothing here calls another model: the gate is HTML parsing,
chunk/section boundary checks, expected-fact matching, and structural
invariants. Conservative by design — any uncertainty rejects.

Validation hierarchy (per the implementation spec):
1. chunk_id
2. current document HTML / structure
3. target section boundaries
4. old_html / new_html
5. ai_explanation only as supplementary evidence
"""

from __future__ import annotations

import html as html_module
import logging
import re

from app.drafting.classifier import CONTENT_STOP, SectionOperation, is_filler_only
from app.superdocs.schemas import PendingChange

logger = logging.getLogger("validator")

_HEADING_RE = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.IGNORECASE | re.DOTALL)

# Placeholder / template-filler markers the model must never emit.
_PLACEHOLDER_PATTERNS = [
    r"please\s+fill",
    r"\[?\s*tbd\s*\]?",
    r"todo\s*:",
    r"placeholder",
]

# Table markup: the SOW template's only table is the Project Details table.
_NEW_TABLE_RE = re.compile(r"<table", re.IGNORECASE)

# Row/cell parsing must survive the markup SuperDocs actually returns, not
# just the pristine shape the template starts with. Once the platform has
# touched the table a row looks like
#   <tr><td colspan="1" rowspan="1"><p><strong>Client</strong></p></td>...
# and a pattern demanding bare <tr><td><strong> matches nothing — which the
# gate reported as "table has no recognizable rows", denied the fill, and
# the denial then wedged the session into a 409 that killed the whole run.
_CHUNK_ID_RE = re.compile(r'data-chunk-id="([^"]+)"', re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TABLE_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)


def _strip(html: str) -> str:
    return html_module.unescape(re.sub(r"<[^>]+>", " ", html or "")).strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").lower().strip()


def _contains_placeholder(html: str) -> bool:
    text = _norm(html)
    return any(re.search(p, text) for p in _PLACEHOLDER_PATTERNS)


def _draft_heading_texts(html: str) -> list[str]:
    return [
        html_module.unescape(re.sub(r"<[^>]+>", "", h)).strip()
        for h in _HEADING_RE.findall(html or "")
    ]


def _contains_heading(html: str) -> bool:
    """A proposed change must never carry heading markup — headings belong
    to the template and are off-limits."""
    return bool(_HEADING_RE.search(html or ""))


_STOP = {
    "the", "a", "an", "and", "or", "is", "are", "be", "of", "to", "for",
    "on", "in", "at", "by", "with", "from", "as", "that", "this", "it",
    "will", "should", "would", "our", "their", "its", "we", "they", "he",
    "she", "not", "no", "but", "so", "if", "then", "than", "also", "very",
    # Function words a paraphrase may freely drop or introduce. Demanded as
    # anchors they forced verbatim phrasing ("missing anchors: ['need',
    # 'where']" against an otherwise perfect sentence); counted as
    # fabrication they flagged ordinary verbs ("['activities', 'does']" for
    # "The project DOES not include ongoing marketing ACTIVITIES").
    "need", "needs", "needed", "where", "when", "which", "who", "does",
    "do", "did", "has", "have", "had", "can", "could", "may", "might",
    "must", "want", "wants", "expect", "expects", "set", "begin", "begins",
    "made", "make", "makes", "been", "being", "was", "were", "there",
    # Ordinary conversational words that are not content in ANY template.
    # _COMMON below was hand-tuned to SOW vocabulary, so on Meeting Minutes,
    # Advice Note and Requirements these read as distinctive: "Joining US
    # today" was rejected as another section's content over the word "us",
    # and "TODAY" / "THREE" / "BECAUSE" were demanded as required anchors.
    "us", "them", "him", "her", "me", "my", "your", "today", "tomorrow",
    "yesterday", "because", "while", "since", "about", "into", "over",
    "each", "every", "any", "all", "both", "own", "self", "able", "still",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "now", "here", "out", "up", "down", "off", "again", "back",
}

# How many ungrounded words separate paraphrase from invention. See the
# calibration note at the fabrication check in validate_proposal.
_UNGROUNDED_MIN = 8

# Words so common in SOW speech that their absence from a proposal proves
# nothing — never used as required anchors.
_COMMON = _STOP | {
    "project", "website", "final", "budget", "total", "start", "starts",
    "scope", "deliver", "delivered", "delivery", "include", "includes",
    "payment", "integration", "client", "provide", "small", "company",
    "online", "complete", "customers", "browse", "products", "cart",
}

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_DATE_RE = re.compile(
    rf"({_MONTHS})[a-z]*\s*\d{{1,2}}(?:st|nd|rd|th)?", re.IGNORECASE
)
_MONEY_RE = re.compile(
    # Must END on a digit. "[\d,]*" is greedy and swallowed the comma after
    # a figure mid-sentence, so "Our total budget is $45,000, and..." yielded
    # the anchor "$45,000," — which SuperDocs never reproduces verbatim, and
    # three correct proposals were rejected for "missing expected content
    # anchors: ['$45,000,']".
    r"\$\s?\d[\d,]*\d|\$\s?\d"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand)\b"
    r"|\bdollars?\b",
    re.IGNORECASE,
)


def facts_preserved_in_html(facts: list[str], html: str) -> tuple[bool, list[str]]:
    """Cumulative preservation check: every anchor of every fact that has
    already been committed must still be present in the current document
    HTML. Catches a later operation silently dropping an earlier
    operation's content (the sequential-edit content-loss failure mode)."""
    text = _norm(html)
    missing: list[str] = []
    for fact in facts:
        for anchor in _fact_anchors(fact):
            # Same morphological tolerance as the proposal gate — a later
            # operation that rewrites "products images" as "product images"
            # has preserved the fact, and reporting that as dropped content
            # rolled back whole batches that were correct.
            if not _anchor_present(anchor, text):
                missing.append(anchor)
    return (not missing), missing


# A relocation shows up as a cluster of the fact's anchors in a foreign
# section, never as one common word.
_MISPLACED_MIN = 2


def _contains_word(haystack: str, needle: str) -> bool:
    """Whole-word containment. Plain `in` matched "product" inside
    "products" and reported correctly-placed content as misplaced."""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def content_landed_in_section(
    updated_html: str, section: str, facts: list[str]
) -> tuple[bool, list[str]]:
    """Did THIS operation's own facts actually land inside its target
    section, not just somewhere in the document? `validate_proposal`'s
    target-section check only fires when `chunk_id` is an existing chunk —
    for a new insertion (`chunk_id == "new"`, the common case for an
    addition; see PendingChange's own docstring) there is no anchor to
    check the proposal against, so that check is silently skipped for
    exactly the case that most needs it. Observed live: an instruction
    correctly targeted "[Target: Out of Scope]", SuperDocs' own edit still
    landed the paragraph under "Next Steps" instead — a real, reproduced
    SuperDocs placement failure the pre-approval proposal check has no way
    to see (the proposal's own new_html fragment carries no location
    information; only the post-approval document does). Runs after
    approval, against the settled document, as an operation-level sibling
    of `facts_preserved_in_html`'s cross-operation check.

    Only flags a CONFIRMED swap — an anchor found within a different named
    heading's own boundary. An anchor that's simply not inside any
    recognized heading at all (trailing/unstructured content) is a
    different failure mode already covered elsewhere, not this check's
    job — collapsing the two would flag ordinary "appended past the last
    heading" shapes as a section swap they aren't."""
    from app.drafting.classifier import _draft_headings

    own_body = _norm(_section_html(updated_html, section))
    other_headings = [h for h in _draft_headings(updated_html) if h != section]
    other_bodies = [_norm(_section_html(updated_html, h)) for h in other_headings]
    misplaced: list[str] = []
    for fact in facts:
        for anchor in _fact_anchors(fact):
            if _contains_word(own_body, anchor):
                continue
            if any(_contains_word(body, anchor) for body in other_bodies):
                misplaced.append(anchor)
    # One stray word is not a relocation. "We'll provide the PRODUCT images"
    # was rolled back whole because "product" also appears inside "browse
    # productS" in Scope of Work — a substring hit on a common noun. A real
    # misplacement moves a phrase, so it shows up as several anchors at once.
    return (len(misplaced) < _MISPLACED_MIN), misplaced


_TRAILING_CONTRAST_RE = re.compile(
    rf"[,;]?\s*\bnot\s+(?:\$\s?[\d,]*\d|(?:{_MONTHS})[a-z]*\s*\d{{1,2}}(?:st|nd|rd|th)?)\s*\.?\s*$",
    re.IGNORECASE,
)


def _word_variants(word: str) -> set[str]:
    """Singular/plural forms of one content word.

    Stem-guessing got this wrong in both directions: stripping "es" turned
    "deliverables" into "deliverabl" (matching neither form), and it could not
    reach "company" from "companies" at all — so a correct singular was
    reported as missing content and the whole Scope of Work operation was
    rejected three times over one letter.
    """
    v = {word}
    if word.endswith("ies") and len(word) > 4:
        v.add(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        v.add(word[:-2])
    if word.endswith("s") and len(word) > 2:
        v.add(word[:-1])
    if word.endswith("y") and len(word) > 2:
        v.add(word[:-1] + "ies")
    v.update({word + "s", word + "es"})
    return v


def _anchor_present(anchor: str, text: str) -> bool:
    """Is this anchor preserved in the proposal?

    Exact substring matching demanded the speaker's own morphology, which a
    correct paraphrase has every right to change. Live: the transcript said
    "the products images" (a Whisper artifact), SuperDocs wrote the correct
    "product images", and the gate rejected the operation for a missing 's'.

    Content words therefore match their singular/plural forms. Dates and
    money never do: those are the values a paraphrase must not alter, and
    "$45,000" vs "$55,000" is exactly the distinction this gate exists to
    catch.
    """
    if anchor in text:
        return True
    if any(ch.isdigit() for ch in anchor):
        return False
    if " " in anchor:
        return False
    for variant in _word_variants(anchor):
        if re.search(rf"(?<!\w){re.escape(variant)}(?!\w)", text):
            return True
    return False


def _fact_anchors(fact: str) -> list[str]:
    """The load-bearing values of one fact: dates and money first (the
    values a paraphrase can't drop), falling back to non-common content
    tokens. Presence of every anchor = semantic preservation. Filler-only
    facts ("Hi.") produce zero anchors — a document must never be required
    to contain conversational filler."""
    if is_filler_only(fact):
        return []
    text = _norm(fact)
    # A contrastive repair names the value it is RETIRING: "the budget is
    # $55,000, not $45,000". Left in, the retired figure becomes a required
    # anchor, so the proposal is rejected for not containing the very value
    # the utterance exists to remove — unpassable by construction, and the
    # live run failed all three attempts on exactly this.
    # Deliberately narrow: only a trailing ", not <money|date>" is dropped,
    # never a general "not" clause, because "the project does not include
    # ongoing marketing" is real Out-of-Scope content that must stay.
    text = _TRAILING_CONTRAST_RE.sub("", text).strip()
    anchors = [re.sub(r"\s+", " ", m.group(0)).lower() for m in _DATE_RE.finditer(text)]
    anchors += [re.sub(r"\s+", " ", m.group(0)).lower() for m in _MONEY_RE.finditer(text)]
    if not anchors:
        # Fallback content anchors use the classifier's canonical function-
        # word set (CONTENT_STOP), NOT this module's _COMMON — _COMMON is
        # the SOW-vocabulary suppression list for contamination checking
        # and would wrongly demand function words like "want"/"have"/"after"
        # as required anchors (Phase 3 benchmark failure).
        anchors = [
            w.strip(".,;:!?$()\"'")
            for w in text.split()
            if w.strip(".,;:!?$()\"'") not in CONTENT_STOP
            and len(w.strip(".,;:!?$()\"'")) > 1
        ]
    return sorted(set(anchors))


def expected_fact_tokens(facts: list[str]) -> list[str]:
    """Distinctive tokens per expected fact — used for the cross-section
    contamination check (tokens that must NOT appear in another section's
    proposal)."""
    tokens: set[str] = set()
    for fact in facts:
        for word in _norm(fact).split():
            w = word.strip(".,;:!?$()\"'")
            if w and w not in _STOP and not w.isdigit() and len(w) > 1:
                tokens.add(w)
    return sorted(tokens)


def ungrounded_tokens(
    new_html: str, own_facts: list[str], all_facts: list[str], draft_html: str
) -> list[str]:
    """Content words in the proposal that trace back to nothing: not this
    operation's facts, not any other operation's facts in the same batch,
    not already present in the document. `facts_preserved_in_html` and the
    per-fact anchor check in `validate_proposal` only prove nothing REQUIRED
    is missing (recall) — they say nothing about whether something
    UNREQUIRED was added (precision). A model can pass every anchor check
    while still inventing a word ("webinar" for "website") or a whole
    sentence ("Our design approach reflects a commitment to modern
    responsibility") that carries no anchor of its own to be missing.
    Conservative like every other check here: any uncertainty rejects, so
    this only flags words absent from the ENTIRE known vocabulary, not
    merely absent from one fact."""
    grounded = set(expected_fact_tokens(own_facts)) | set(expected_fact_tokens(all_facts))
    grounded |= {
        w.strip(".,;:!?$()\"'")
        for w in _norm(_strip(draft_html)).split()
        if w.strip(".,;:!?$()\"'")
    }
    # _strip() first — new_html is raw markup ("<p>The...15th.</p>"), and
    # splitting on whitespace without removing tags first turns tag-adjacent
    # words into garbage tokens ("<p>the", "15th.</p>") that can never be
    # grounded, which would make this check reject almost everything.
    new_text = _norm(_strip(new_html))
    tokens: set[str] = set()
    for word in new_text.split():
        w = word.strip(".,;:!?$()\"'")
        if (
            w and w not in _STOP and w not in _COMMON and w not in grounded
            and not w.isdigit() and len(w) > 2
        ):
            tokens.add(w)
    return sorted(tokens)


# A single shared word proves nothing — real cross-section contamination
# shows up as a cluster of another operation's distinctive vocabulary. At a
# threshold of one, ordinary overlap killed whole documents: 'us', 'self'
# and 'data' each rejected a batch through all three attempts.
_FOREIGN_MIN = 2
_FOREIGN_MIN_LEN = 4


def foreign_fact_tokens(own_facts: list[str], all_facts: list[str]) -> list[str]:
    """Tokens that belong to OTHER operations in the batch and are
    distinctive enough to prove contamination if they appear in this
    operation's proposal. Words in _COMMON (project, website, scope, ...)
    are deliberately excluded — they legitimately appear across sections."""
    # Seeded from the raw words too, not just expected_fact_tokens: that
    # helper folds "September 15" into a date anchor and drops the bare
    # number, so a Timeline operation's own "15"/"30" were absent from `own`
    # and got flagged as another section's content — rejecting the very
    # dates the operation exists to write.
    own = set(expected_fact_tokens(own_facts))
    for fact in own_facts:
        for word in _norm(fact).split():
            w = word.strip(".,;:!?$()\"'")
            if w:
                own.add(w)
    foreign: set[str] = set()
    for fact in all_facts:
        for word in _norm(fact).split():
            w = word.strip(".,;:!?$()\"'")
            if (
                w and w not in _STOP and w not in _COMMON
                and w not in own and len(w) >= _FOREIGN_MIN_LEN
            ):
                foreign.add(w)
    return sorted(foreign)


def _section_html(draft_html: str, section: str) -> str:
    """The HTML between the target section's heading and the next heading —
    the authoritative section boundary (chunk ids live inside it). Heading
    text in the document is HTML-entity-encoded (& → &amp;), so the match
    pattern must mirror that encoding."""
    pattern = re.escape(section.replace("&", "&amp;"))
    m = re.search(
        rf"<h2[^>]*>[^<]*{pattern}[^<]*</h2>(.*?)(?=<h[12][^>]*>|$)",
        draft_html or "", re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


def validate_proposal(
    op: SectionOperation,
    change: PendingChange,
    draft_html: str,
    foreign_tokens: list[str] | None = None,
    all_facts: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Validate one proposed change against the operation's ground truth.
    Returns (accepted, failures). Any failure → reject the proposal.
    `foreign_tokens` are distinctive tokens of OTHER operations in the same
    batch — a proposal carrying them is contaminated. `all_facts` (every
    fact in the whole batch, not just this operation's) grounds the
    ungrounded-content check below — passed separately from foreign_tokens
    because that list already excludes _COMMON words this check needs to
    keep excluded too, but the two checks catch different defects
    (contamination vs. fabrication) and reuse the same source list."""
    failures: list[str] = []
    new_html = change.new_html or ""
    old_html = change.old_html or ""

    # --- structural invariants (apply to every operation) -----------------
    # A heading is allowed in exactly one case: the operation targets a
    # section the document does not have yet, and the proposal creates that
    # one heading. Sections are no longer seeded into the starter document,
    # so the first fact belonging to a section is what brings its heading
    # into existence — a blanket ban would make every such section
    # unreachable. Any OTHER heading, or a changed one, still fails.
    if _contains_heading(new_html):
        proposed = [
            html_module.unescape(re.sub(r"<[^>]+>", "", h)).strip()
            for h in _HEADING_RE.findall(new_html)
        ]
        creating_target = (
            op.section is not None
            and proposed == [op.section]
            and op.section not in _draft_heading_texts(draft_html)
        )
        if not creating_target:
            failures.append("proposal contains heading markup — headings must never change")
    if _contains_placeholder(new_html):
        failures.append("proposal contains placeholder/filler text (e.g. 'Please fill:')")
    if _NEW_TABLE_RE.search(new_html) and "<table" not in (old_html or ""):
        failures.append("proposal creates a new table — only the template's table may exist")
    if not new_html.strip():
        failures.append("proposal carries no content")

    # --- target-section validation -----------------------------------------
    if op.section is not None:
        target_body = _section_html(draft_html, op.section)
        change_id = change.chunk_id or "new"
        # Only meaningful when the section actually owns a chunk to anchor
        # to. An untouched section's body is "<p><p></p></p>" — a non-empty
        # string carrying no chunk id at all, so `change_id not in
        # target_body` was true for EVERY id and the first write into any
        # empty section was rejected no matter what SuperDocs proposed.
        # Confirmed live: Scope of Work denied four times running while
        # Timeline and Budget passed first try purely because SuperDocs
        # happened to return "new" for those. Placement is still enforced —
        # content_landed_in_section checks the resulting HTML after the
        # edit, which is the check that can actually be satisfied here.
        section_chunk_ids = _CHUNK_ID_RE.findall(target_body)
        if change_id != "new" and section_chunk_ids and change_id not in section_chunk_ids:
            # The change anchors to a chunk outside the intended section.
            failures.append(
                f"proposal targets chunk {change_id} which is outside section '{op.section}'"
            )

    # --- content validation (semantic anchors, not exact wording) -----------
    for fact in op.facts:
        anchors = _fact_anchors(fact)
        if anchors:
            new_text = _norm(new_html)
            missing = [a for a in anchors if not _anchor_present(a, new_text)]
            if missing:
                failures.append(f"proposal is missing expected content anchors: {missing[:5]}")

    # --- cross-section contamination ----------------------------------------
    if foreign_tokens:
        new_text = _norm(new_html)
        foreign = [t for t in foreign_tokens if t in new_text]
        if len(foreign) >= _FOREIGN_MIN:
            failures.append(f"proposal contains content from another section: {foreign[:5]}")

    # --- fabrication (precision, not recall) ---------------------------------
    # The anchor check above only proves nothing expected is missing; it
    # says nothing about invented content that carries no anchor of its own.
    # Threshold, not zero-tolerance. Calibrated against a full benchmark run
    # rather than intuition: legitimate prose clustered at 2-3 ungrounded
    # words ("the project is SCHEDULED to start on September 15" — accurate,
    # every fact intact), while genuine fabrication ran 5-25 ("a modern,
    # HIGH-PERFORMANCE online STORE with SEAMLESS FUNCTIONALITY ACROSS ALL
    # DESKTOP and mobile DEVICES" — specifics nobody said). At 2 this check
    # rejected correct sentences until every retry was spent and the section
    # exported blank, which is a worse failure than slightly verbose prose.
    if all_facts is not None:
        ungrounded = ungrounded_tokens(new_html, op.facts, all_facts, draft_html)
        if len(ungrounded) >= _UNGROUNDED_MIN:
            failures.append(f"proposal contains unsupported content not traceable to the source: {ungrounded[:5]}")
            # Diagnostic-only, temporary: full context for the false-positive
            # vs. genuine-catch question — remove once resolved.
            logger.warning(
                "UNGROUNDED CHECK FIRED: ungrounded=%s | op.section=%r | op.facts=%r | "
                "all_facts=%r | new_html=%r",
                ungrounded, op.section, op.facts, all_facts, new_html,
            )

    return (not failures), failures


def _table_rows(html: str) -> list[tuple[str, str]]:
    """(label, value) per row, read through whatever wrapper markup the
    cells carry — _strip removes tags and unescapes entities, so
    "<p><strong>Client</strong></p>" and "<td>Client</td>" both read as
    "Client"."""
    rows: list[tuple[str, str]] = []
    for row_html in _TABLE_ROW_RE.findall(html or ""):
        cells = [_strip(c) for c in _TABLE_CELL_RE.findall(row_html)]
        if len(cells) >= 2:
            rows.append((cells[0], cells[1]))
    return rows


def validate_table_fill(op: SectionOperation, change: PendingChange) -> tuple[bool, list[str]]:
    """Validate a Project Details table-cell fill — a different shape from
    a section-body edit, so it gets its own gate rather than overloading
    `validate_proposal`: row count and every OTHER row's value must stay
    identical to `old_html`; only the target field's empty cell may change,
    and only to the expected value. The heading check doesn't apply here —
    a table row has no <h1>/<h2> of its own to protect — but placeholder
    text is still never acceptable."""
    failures: list[str] = []
    new_html = change.new_html or ""
    old_html = change.old_html or ""

    if _contains_placeholder(new_html):
        failures.append("proposal contains placeholder/filler text")

    old_rows = _table_rows(old_html)
    new_rows = _table_rows(new_html)
    if not new_rows:
        failures.append("proposal's table has no recognizable rows")
        return (not failures), failures
    if old_rows and len(new_rows) != len(old_rows):
        failures.append(f"table row count changed: {len(old_rows)} -> {len(new_rows)}")

    old_by_label = dict(old_rows)
    changed: list[tuple[str, str]] = []
    for label, value in new_rows:
        old_value = old_by_label.get(label)
        if old_value is None:
            failures.append(f"table has a row not in the original: {label!r}")
            continue
        if value != old_value:
            changed.append((label, value))

    if len(changed) != 1:
        failures.append(f"expected exactly one changed cell, got {len(changed)}: {changed}")
    else:
        label, value = changed[0]
        if label != op.table_field:
            failures.append(f"wrong field changed: expected {op.table_field!r}, got {label!r}")
        elif _norm(value) != _norm(op.table_value or ""):
            failures.append(f"expected value {op.table_value!r}, got {value!r}")

    return (not failures), failures


# Corrections need the pre-edit value as ground truth, which only the caller
# (session.py) carries — hence the separate entry point.

def validate_correction(
    op: SectionOperation,
    change: PendingChange,
    draft_html: str,
    expected_old_value: str | None,
    expected_new_value: str | None,
) -> tuple[bool, list[str]]:
    """Correction-specific gate. The caller extracts the old value (from the
    current draft) and the new value (from the correction text); the proposal
    must edit the SAME chunk and replace old with new."""
    failures: list[str] = []
    new_html = change.new_html or ""
    old_html = change.old_html or ""

    if change.operation != "edit":
        failures.append("correction proposal is not an edit operation")
    if _contains_heading(new_html):
        failures.append("proposal contains heading markup")
    if _contains_placeholder(new_html):
        failures.append("proposal contains placeholder text")

    if expected_old_value and expected_new_value:
        old_norm = _norm(expected_old_value)
        new_norm = _norm(expected_new_value)
        new_text = _norm(new_html)
        if old_norm and old_norm not in _norm(old_html):
            failures.append("proposal's old_html does not contain the value being corrected")
        if new_norm and new_norm not in new_text:
            failures.append("proposal's new_html does not contain the replacement value")
        if old_norm and old_norm in new_text:
            failures.append("correction keeps the old value alongside the new one")

    return (not failures), failures
