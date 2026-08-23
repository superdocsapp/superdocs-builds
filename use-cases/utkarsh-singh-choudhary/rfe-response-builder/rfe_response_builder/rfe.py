"""
Domain logic for the Request-for-Evidence (RFE) Response Builder.

Kept dependency-free and pure (no `requests`, no SuperDocs client) so
every rule here -- how a notice gets split into discrete requests, how a
request is matched to what the original petition already argued, how
new evidence needed is identified, how exhibits get numbered, and how
coverage is proven -- is unit-testable without network access.

All case data is synthetic. No real filings.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .embeddings import EmbeddingProvider, get_default_provider  # noqa: F401 (EmbeddingProvider used in type hints)

logger = logging.getLogger(__name__)

# --- 1. Parsing the officer's notice into discrete requests -----------------
#
# RFE notices are conventionally structured as a numbered or lettered list
# of distinct requests/issues. We parse on that structure rather than
# free-form NLP, so parsing is deterministic and testable. A notice with no
# recognizable list structure falls back to one single "request" covering
# the whole body, so nothing is silently dropped.

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"(?:Issue|Request|Item)\s+(\d+)[:.\)]\s*"     # "Issue 1:", "Request 2."
    r"|(\d+)[.\)]\s+"                                # "1. " / "1) "
    r"|([A-Z])[.\)]\s+"                              # "A. " / "A) "
    r")",
    re.MULTILINE,
)

_STOPWORDS = {
    "this", "that", "with", "from", "have", "must", "shall",
    "will", "your", "been", "additional", "evidence", "please",
    "provide", "regarding", "should", "which", "there", "their",
}


def _keywords(text: str) -> set[str]:
    """Cheap, deterministic keyword set -- lowercased alphabetic tokens of
    length > 3, stopword-free enough for this domain without pulling in an
    NLP dependency. Shared by every matcher in this module so scoring is
    consistent across prior-petition and new-evidence matching."""
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return {t for t in tokens if len(t) > 3 and t not in _STOPWORDS}


_STEM_SUFFIXES = (
    "ization", "isation", "ements", "ities", "tion", "ment", "ness",
    "ance", "ence", "ings", "edly", "ing", "ied", "ies", "ed", "es", "ly", "s",
)


def _stem(word: str) -> str:
    """Suffix-stripping stemmer (Porter-lite): 'specialization',
    'specialized', 'specializes' all reduce to 'special'. Deliberately
    crude and stdlib-only -- this catches morphological variants that
    exact keyword overlap misses, but it is NOT semantic matching (it
    won't connect 'expertise' to 'experience', for instance). Used only
    by `fuzzy_matches` below, never by the strict `best_matches` scoring
    that citations are built from."""
    longest = word
    for suf in _STEM_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            candidate = word[: -len(suf)]
            if len(candidate) < len(longest):
                longest = candidate
    return longest


def _stemmed_keywords(text: str) -> set[str]:
    return {_stem(t) for t in _keywords(text)}


@dataclass
class RFERequest:
    request_id: str
    text: str

    @property
    def keywords(self) -> set[str]:
        return _keywords(self.text)


def parse_rfe_notice(notice_text: str) -> list[RFERequest]:
    """Split an officer's RFE notice into its discrete numbered/lettered
    requests. Never drops content: if no list markers are found, the whole
    notice becomes a single request rather than being silently ignored."""
    matches = list(_LIST_ITEM_RE.finditer(notice_text))
    if not matches:
        stripped = notice_text.strip()
        if not stripped:
            return []
        return [RFERequest(request_id="1", text=stripped)]

    requests: list[RFERequest] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(notice_text)
        body = notice_text[start:end].strip()
        if not body:
            continue
        label = m.group(1) or m.group(2) or m.group(3) or str(i + 1)
        requests.append(RFERequest(request_id=str(label), text=body))
    return requests


# --- 2. What the original petition already argued ---------------------------

@dataclass
class PetitionArgument:
    """One point the original petition already made, with a page/section
    reference so a matched citation is traceable, not invented."""
    topic_id: str
    text: str
    source_ref: str  # e.g. "Petition Letter, p. 4" -- must trace to a real place


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


def arguments_from_free_text(source_name: str, text: str, min_length: int = 40) -> list[PetitionArgument]:
    """Turns an arbitrary uploaded supporting document (petition letter,
    employer letter, expert opinion, etc.) into candidate PetitionArguments
    by splitting on blank lines -- one argument per paragraph, source_ref
    pointing at that exact paragraph in that exact document.

    This is deliberately paragraph-level keyword search, not semantic/vector
    retrieval: every source_ref this produces is directly traceable to a
    real paragraph a human uploaded, so a matched citation can never point
    at something that doesn't exist in the record. Multiple documents can
    each be run through this and their results concatenated onto a
    PriorPetition's `arguments` list, which is how multi-document support
    is wired into the web UI -- see webapp/app.py's `supporting_docs` field.
    Short fragments (headers, signature blocks) are dropped via min_length
    so they don't pollute keyword matching with noise.
    """
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    return [
        PetitionArgument(
            topic_id=f"{source_name}-{i + 1}",
            text=p,
            source_ref=f"{source_name}, \u00b6{i + 1}",
        )
        for i, p in enumerate(paragraphs)
        if len(p) >= min_length
    ]


@dataclass
class PriorPetition:
    arguments: list[PetitionArgument] = field(default_factory=list)

    def best_matches(self, request: RFERequest, top_n: int = 2) -> list[PetitionArgument]:
        """Deterministic keyword-overlap scoring, ranked -- no LLM call,
        fully testable. Returns up to `top_n` arguments with score > 0,
        best first. A request that legitimately spans two prior petition
        arguments now surfaces both instead of only the single strongest
        match."""
        scored = []
        for arg in self.arguments:
            score = len(request.keywords & _keywords(arg.text))
            if score > 0:
                scored.append((score, arg))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [arg for _, arg in scored[:top_n]]

    def best_match(self, request: RFERequest) -> PetitionArgument | None:
        """Backwards-compatible single-best-match accessor, built on top
        of `best_matches`. Returns `None` (never a fabricated match) when
        nothing overlaps meaningfully."""
        matches = self.best_matches(request, top_n=1)
        return matches[0] if matches else None

    def fuzzy_matches(self, request: RFERequest, top_n: int = 2,
                       min_confidence: float = 0.05) -> list[tuple[PetitionArgument, float]]:
        """Stemmed-keyword fallback, used ONLY when `best_matches` finds
        nothing for this request. Addresses the real gap where an RFE item
        phrased as "does not establish specialized expertise" and a
        petition arguing "extensive technical experience" share zero exact
        keywords but are clearly related.

        This is deliberately kept separate from `best_matches` rather than
        folded into it: `best_matches` results are cited directly in the
        drafted response as prior-petition support, so they must stay
        exact-keyword-overlap precise. `fuzzy_matches` results are surfaced
        to a human as an unverified suggestion ("possible related prior
        argument -- verify before citing") and are never themselves turned
        into a source_ref or fed into the drafting instruction -- that
        would risk citing a paraphrase as if it were the petition's actual
        wording. Confidence is Jaccard similarity over stemmed keyword
        sets (0-1), not a calibrated probability.
        """
        req_stems = _stemmed_keywords(request.text)
        if not req_stems:
            return []
        scored = []
        for arg in self.arguments:
            arg_stems = _stemmed_keywords(arg.text)
            if not arg_stems:
                continue
            overlap = req_stems & arg_stems
            if not overlap:
                continue
            confidence = len(overlap) / len(req_stems | arg_stems)
            if confidence >= min_confidence:
                scored.append((confidence, arg))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(arg, round(conf, 2)) for conf, arg in scored[:top_n]]

    def semantic_matches(self, request: RFERequest, top_n: int = 2,
                          min_similarity: float = 0.12,
                          provider: "EmbeddingProvider | None" = None) -> list[tuple[PetitionArgument, float]]:
        """Third-tier fallback, tried ONLY when both `best_matches` (exact
        keyword overlap) and `fuzzy_matches` (stemmed keyword overlap) find
        nothing for this request.

        `provider` (see `embeddings.py`) determines what "semantic" means
        here. Defaults to `embeddings.get_default_provider()`, which is
        the zero-cost, zero-network `TfidfEmbeddingProvider` UNLESS
        `EMBEDDINGS_API_KEY` is set in the environment, in which case it's
        a real embeddings-API provider instead.

        Important honesty note that still applies to the DEFAULT
        (TF-IDF) provider: it requires literal shared tokens between the
        two texts to produce a nonzero score, so it does NOT connect true
        zero-overlap synonyms like "expertise" and "experience" if
        nothing else in the two texts overlaps either. What it DOES
        catch, that `best_matches`/`fuzzy_matches` miss: (a) short but
        meaningful shared tokens below this module's 4-character keyword
        floor (e.g. "law", "R&D", "PhD"), and (b) documents that share a
        handful of significant terms diluted across a lot of other text.
        For genuine synonym-level connection with a real embeddings
        model, configure `EMBEDDINGS_API_KEY` -- see `embeddings.py`'s
        module docstring. Either way, if the provider itself fails
        (missing scikit-learn, an embeddings-API outage), this degrades
        to returning [] rather than raising, so the rest of the pipeline
        (which has never depended on it) is unaffected.

        Exactly like `fuzzy_matches`, results here are NEVER used as a
        citation and NEVER fed into `build_response_instruction` -- they
        surface only as an explicit "possible related argument, UNVERIFIED,
        semantic-similarity-only" suggestion in the dry-run output and the
        review UI, gated on a human confirming before it's ever cited.
        Confidence is a similarity score (0-1), not a calibrated
        probability, and is deliberately treated as noisier than
        `fuzzy_matches`' Jaccard score -- a weaker, "worth a human's
        eyes" signal, not a stronger one, regardless of which provider
        produced it.
        """
        if not self.arguments:
            return []
        provider = provider or get_default_provider()
        candidate_texts = [a.text for a in self.arguments]
        sims = provider.similarities(request.text, candidate_texts)
        if not sims:
            return []

        scored = [
            (float(sim), arg)
            for sim, arg in zip(sims, self.arguments)
            if sim >= min_similarity
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(arg, round(sim, 2)) for sim, arg in scored[:top_n]]

    def unverified_suggestions(self, request: RFERequest, top_n: int = 2,
                                provider: "EmbeddingProvider | None" = None,
                                ) -> tuple[str, list[tuple[PetitionArgument, float]]]:
        """Single entry point for 'we found nothing exact, but here's an
        unverified lead' -- tries `fuzzy_matches` (stemmed, higher trust)
        first, and only falls through to `semantic_matches` (embeddings-
        based, lower trust, catches true synonyms if a real provider is
        configured) if fuzzy also found nothing. Returns (tier_name,
        matches) where tier_name is one of "fuzzy", "semantic", or "none"
        -- callers (dry-run output, review UI) use tier_name to label the
        suggestion's trust level to the human reviewing it. Only called
        by callers after `best_matches` already returned []; never itself
        feeds a citation.
        """
        fuzzy = self.fuzzy_matches(request, top_n=top_n)
        if fuzzy:
            return "fuzzy", fuzzy
        semantic = self.semantic_matches(request, top_n=top_n, provider=provider)
        if semantic:
            return "semantic", semantic
        return "none", []


# --- 3. New evidence needed --------------------------------------------------

@dataclass
class NewEvidenceEntry:
    """One catalog entry describing a category of evidence that could be
    gathered for a case. This is NOT a fabricated fact about the client --
    it's a description of an evidence *type* (e.g. "certified translation
    of a foreign-language document"), sourced from a supplied catalog file
    so the tool never invents specifics it wasn't given."""
    topic_id: str
    description: str
    exhibit_label: str  # e.g. "Certified Translation"


@dataclass
class NewEvidenceCatalog:
    entries: list[NewEvidenceEntry] = field(default_factory=list)

    def best_matches(self, request: RFERequest, top_n: int = 2) -> list[NewEvidenceEntry]:
        """Same deterministic keyword-overlap approach as prior-petition
        matching, applied to the evidence catalog. Returns [] rather than
        guessing when nothing in the catalog overlaps with the request."""
        scored = []
        for entry in self.entries:
            score = len(request.keywords & _keywords(entry.description))
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:top_n]]


# --- 4. Response drafting instruction ----------------------------------------

def build_response_instruction(request: RFERequest, prior_argument: PetitionArgument | None,
                                new_evidence_note: str | None = None,
                                legal_framework_note: str | None = None) -> str:
    """Builds the natural-language instruction sent to SuperDocs for ONE
    RFE request. Deliberately instructs the AI to engage the officer's
    specific concern rather than restate the petition -- the brief's own
    'what strong looks like' bar -- and to flag (never invent) new
    evidence needed.

    `legal_framework_note`, if given (see classify.py), is a short,
    conservative regulatory-anchor note for the notice's classified
    petition type (e.g. the 8 CFR provision an H-1B specialty-occupation
    RFE would typically be analyzed under). It's framed to the drafting
    model as background context to inform tone/structure, explicitly NOT
    as a citation to insert verbatim -- the drafted text should still
    only cite what's in the record, consistent with the "do not invent
    citations" instruction below."""
    if prior_argument:
        prior_block = (
            f"The original petition already argued this point (see {prior_argument.source_ref}): "
            f"\"{prior_argument.text}\". Do not simply restate this -- directly address the "
            f"officer's specific concern below, using this prior argument only where it "
            f"actually answers the concern."
        )
    else:
        prior_block = (
            "The original petition did not clearly address this point. Say so explicitly "
            "rather than inventing a prior argument, and focus the response on the new "
            "evidence needed."
        )

    evidence_block = f" New evidence to reference: {new_evidence_note}." if new_evidence_note else ""
    framework_block = (
        f"\n\nBackground context on the likely filing type (for tone/structure only -- do not "
        f"quote this verbatim or treat it as a citation to insert; only cite what's actually "
        f"in the record): {legal_framework_note}"
        if legal_framework_note else ""
    )

    return (
        f"Draft a response section titled \"{response_section_heading(request.request_id)}\" "
        f"addressing this RFE request from the officer (item {request.request_id}): "
        f"\"{request.text}\"\n\n"
        f"{prior_block}{evidence_block}{framework_block}\n\n"
        f"Write it as a direct, specific response to the officer's stated concern -- "
        f"not a restatement of the original petition. Do not invent facts, evidence, "
        f"or citations that were not given to you above."
    )


def new_evidence_note_from_entries(entries: list[NewEvidenceEntry]) -> str | None:
    """Joins matched evidence-catalog entries into the note string consumed
    by `build_response_instruction`. Kept separate from matching so the
    instruction builder stays agnostic to how evidence was identified."""
    if not entries:
        return None
    return "; ".join(e.description for e in entries)


# --- 4b. Answer quality gate ---------------------------------------------------
#
# A successful HTTP call to SuperDocs is not the same thing as a substantive
# answer. If the model replies "I don't have enough information to address
# this" or similar, the original code still marked the item ANSWERED because
# nothing raised. This checks the actual reply text for the shape of a
# non-answer so the checklist can't silently lie.

_NON_ANSWER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bi (don'?t|do not) have (enough|sufficient) (information|context|detail)",
        r"\b(unable|cannot|can'?t) to (address|answer|respond to)",
        r"\bplease provide (more|additional) (information|context|detail)",
        r"\bno (relevant|matching) (information|content) (was )?found",
        r"^\s*(sorry|apolog)",
    ]
]

_MIN_SUBSTANTIVE_LENGTH = 40


def is_substantive_reply(reply_text: str | None) -> bool:
    """True if `reply_text` looks like an actual drafted response rather
    than a refusal/hedge/empty reply. Deliberately conservative (pattern
    match + length floor, not sentiment analysis) so it's predictable and
    testable, matching the rest of this module's determinism bar. A reply
    that fails this check means the item is NOT ANSWERED even though the
    API call itself succeeded."""
    if not reply_text or not reply_text.strip():
        return False
    if len(reply_text.strip()) < _MIN_SUBSTANTIVE_LENGTH:
        return False
    return not any(p.search(reply_text) for p in _NON_ANSWER_PATTERNS)


# --- 4c. Evidence status classification -----------------------------------------

class EvidenceStatus:
    """Distinguishes what stage a piece of evidence is at for a given RFE
    request, so the response/checklist can say more than just 'evidence
    matched' -- an attorney needs to know whether something was already
    submitted (and is now being re-cited) versus genuinely new."""
    ALREADY_SUBMITTED = "already_submitted"  # matched a prior-petition argument, no new evidence needed
    NEW_EVIDENCE_IDENTIFIED = "new_evidence_identified"  # matched a catalog entry not in the prior petition
    NEEDS_ATTORNEY_REVIEW = "needs_attorney_review"  # no prior argument AND no catalog match


def classify_evidence_status(prior_matches: list[PetitionArgument],
                              evidence_matches: list[NewEvidenceEntry]) -> str:
    """One deterministic rule, applied per RFE item: prior argument found ->
    already submitted; no prior argument but catalog evidence found -> new
    evidence identified; neither -> flag for attorney review rather than
    silently leaving a gap. Never infers evidence that wasn't supplied."""
    if prior_matches:
        return EvidenceStatus.ALREADY_SUBMITTED
    if evidence_matches:
        return EvidenceStatus.NEW_EVIDENCE_IDENTIFIED
    return EvidenceStatus.NEEDS_ATTORNEY_REVIEW


# --- 5. Exhibit assembly ------------------------------------------------------

@dataclass
class Exhibit:
    number: int
    label: str
    description: str
    request_ids: list[str]


def build_exhibit_list(requests: list[RFERequest],
                        evidence_matches: dict[str, list[NewEvidenceEntry]]) -> list[Exhibit]:
    """Assembles a numbered exhibit list from the new evidence identified
    per request, in notice order. The same evidence-catalog entry matched
    against multiple requests becomes ONE exhibit referenced by every
    request it supports, rather than duplicate exhibits -- so exhibit
    numbers stay stable and non-redundant."""
    exhibits_by_topic: dict[str, Exhibit] = {}
    next_number = 1
    for r in requests:
        for entry in evidence_matches.get(r.request_id, []):
            existing = exhibits_by_topic.get(entry.topic_id)
            if existing:
                if r.request_id not in existing.request_ids:
                    existing.request_ids.append(r.request_id)
            else:
                exhibits_by_topic[entry.topic_id] = Exhibit(
                    number=next_number,
                    label=entry.exhibit_label,
                    description=entry.description,
                    request_ids=[r.request_id],
                )
                next_number += 1
    return sorted(exhibits_by_topic.values(), key=lambda ex: ex.number)


# --- 6. Coverage checklist ----------------------------------------------------

@dataclass
class CoverageRow:
    request_id: str
    request_text: str
    answered: bool
    matched_prior_arguments: list[str]  # source_refs, possibly empty
    new_evidence: list[str]             # matched evidence descriptions, possibly empty
    exhibit_numbers: list[int]          # exhibit numbers supporting this request
    response_section: str               # the heading in the exported doc that answers this item
    evidence_status: str = EvidenceStatus.NEEDS_ATTORNEY_REVIEW

    @property
    def matched_prior_argument(self) -> str | None:
        """Backwards-compatible single-value accessor."""
        return self.matched_prior_arguments[0] if self.matched_prior_arguments else None


def response_section_heading(request_id: str) -> str:
    """Single source of truth for the section title used both when
    instructing SuperDocs to draft an item and when the coverage checklist
    reports which section answers it -- so 'maps every request to the part
    of the response that answers it' is a real, checkable link, not two
    independently-worded strings that happen to agree today."""
    return f"Response to Item {request_id}"


def build_coverage_checklist(requests: list[RFERequest],
                              matches: dict[str, list[PetitionArgument] | PetitionArgument | None],
                              answered_ids: set[str],
                              evidence_matches: dict[str, list[NewEvidenceEntry]] | None = None,
                              exhibits: list[Exhibit] | None = None) -> list[CoverageRow]:
    """Maps every request in the notice to whether it was answered --
    the brief's explicit requirement that nothing in the notice goes
    unanswered -- plus which prior-petition citations, new evidence, and
    exhibits support that answer, and which section of the exported
    document actually contains that answer. `answered_ids` comes from
    which requests actually got a *substantive* drafted response (see
    `is_substantive_reply`), never assumed from API success alone.

    `matches` accepts either the new list-per-request form or the legacy
    single-PetitionArgument-or-None form, for backwards compatibility.
    """
    evidence_matches = evidence_matches or {}
    exhibit_by_request: dict[str, list[int]] = {}
    for ex in exhibits or []:
        for rid in ex.request_ids:
            exhibit_by_request.setdefault(rid, []).append(ex.number)

    rows = []
    for r in requests:
        raw_match = matches.get(r.request_id)
        if raw_match is None:
            match_list: list[PetitionArgument] = []
        elif isinstance(raw_match, list):
            match_list = raw_match
        else:
            match_list = [raw_match]

        row_evidence = evidence_matches.get(r.request_id, [])
        rows.append(
            CoverageRow(
                request_id=r.request_id,
                request_text=r.text,
                answered=r.request_id in answered_ids,
                matched_prior_arguments=[m.source_ref for m in match_list],
                new_evidence=[e.description for e in row_evidence],
                exhibit_numbers=sorted(exhibit_by_request.get(r.request_id, [])),
                response_section=response_section_heading(r.request_id) if r.request_id in answered_ids else "(not answered)",
                evidence_status=classify_evidence_status(match_list, row_evidence),
            )
        )
    return rows


def all_requests_answered(rows: list[CoverageRow]) -> bool:
    return all(row.answered for row in rows)


# --- 7. Filesystem safety -----------------------------------------------------

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_case_id(case_id: str) -> str:
    """Case IDs get interpolated straight into output filenames. Strip
    anything that isn't alphanumeric/dot/dash/underscore so a stray `/`,
    `..`, or shell-special character in user-supplied input can't escape
    the output directory or otherwise misbehave as a filename."""
    cleaned = _SAFE_ID_RE.sub("-", case_id).strip("-.")
    if not cleaned:
        raise ValueError(f"case_id {case_id!r} has no usable characters for a filename")
    return cleaned
