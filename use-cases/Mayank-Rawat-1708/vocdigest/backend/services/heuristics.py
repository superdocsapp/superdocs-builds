"""
@file: backend/services/heuristics.py
@description: LLM-free implementations of the analysis steps, used when Groq is
    unavailable, out of credits, or not configured. Quality is genuinely lower than the
    model path — these are keyword and frequency methods, not understanding — so every
    function reports that it ran in degraded mode and the digest states it plainly
    rather than presenting heuristic output as if a model produced it.
@flow: a node detects Groq is unavailable -> calls the matching heuristic_* function ->
    receives the same shape the LLM path returns, plus degraded=True -> the node logs a
    DEGRADED decision and continues -> draft_node adds a methodology paragraph naming
    exactly which stages were heuristic.
@dependencies:
    - re / collections: keyword matching and frequency counting only
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Content that is clearly not a customer describing a problem. Deliberately narrow: a
# false positive here silently discards real signal, which is worse than keeping noise.
_NON_SUPPORT = re.compile(
    r"unsubscribe|view (this|in) (email|browser)|do not reply|noreply@"
    r"|automated (message|notification)|this is an automated"
    r"|% off|limited time offer|click here to (buy|shop)|newsletter",
    re.IGNORECASE,
)

# Product-area keywords. Order matters: the first match wins, so more specific areas
# are listed before general ones.
_AREAS: list[tuple[str, re.Pattern[str]]] = [
    ("export", re.compile(r"\bexport|download(ing)?\b|csv|xlsx|spreadsheet", re.I)),
    ("mobile app", re.compile(r"\b(ios|iphone|ipad|android|mobile app)\b|app crash", re.I)),
    ("notifications", re.compile(r"notification|email alert|digest email|reminder", re.I)),
    ("billing", re.compile(r"billing|invoice|payment|subscription|plan|charge|refund", re.I)),
    ("dashboard", re.compile(r"dashboard|overview page|home ?screen|load(ing)? time", re.I)),
    ("search", re.compile(r"\bsearch|filter|sort(ing)?\b", re.I)),
    ("permissions", re.compile(r"permission|access denied|not authori[sz]ed|role", re.I)),
    ("integrations", re.compile(r"integration|webhook|\bapi\b|sso|okta|slack", re.I)),
    ("performance", re.compile(r"\bslow|lag(gy|ging)?|timeout|hang(s|ing)?|freeze", re.I)),
]

_BLOCKED = re.compile(
    r"can(no|')t (use|access|complete|do)|unable to|blocked|blocking|stuck"
    r"|does(n't| not) work|not working|broken|fails?|failing|unusable",
    re.I,
)
_FRUSTRATED = re.compile(
    r"frustrat|ridiculous|unacceptable|terrible|awful|furious|angry|fed up"
    r"|still (not|broken)|again|third time|weeks?|escalat",
    re.I,
)
_POSITIVE = re.compile(r"thank|great|excellent|love|appreciate|brilliant|works well", re.I)
_HIGH_SEVERITY = re.compile(
    r"urgent|critical|production|revenue|deadline|all (our|of our) (users|customers)"
    r"|entire team|blocking|cannot work",
    re.I,
)

# Words too common to distinguish one theme from another.
_STOPWORDS = {
    "the","a","an","and","or","but","is","are","was","were","be","been","being","to","of",
    "in","on","at","for","with","from","by","as","it","its","this","that","these","those",
    "i","we","you","they","my","our","your","their","me","us","them","have","has","had",
    "do","does","did","not","no","yes","can","cannot","could","would","should","will",
    "when","what","why","how","there","then","than","very","just","also","get","got",
    "please","hi","hello","thanks","thank","help","issue","problem","support","team",
    "any","all","some","more","most","other","again","still","now","one","two",
}


@dataclass(slots=True)
class HeuristicResult:
    """Output plus an explicit statement that it came from the degraded path."""

    data: Any
    degraded: bool = True
    method: str = "heuristic"
    caveats: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower())
        if w not in _STOPWORDS
    ]


def heuristic_classify(texts: list[str]) -> HeuristicResult:
    """Decide which records are support conversations, without a model.

    Biased towards keeping records. A discarded conversation is invisible in the final
    digest, so the failure mode of over-filtering is silent under-reporting — worse than
    carrying some noise into the clustering step.
    """
    results = []
    for index, text in enumerate(texts):
        is_noise = bool(_NON_SUPPORT.search(text))
        too_short = len(text.strip()) < 15
        relevant = not (is_noise or too_short)
        results.append(
            {
                "index": index,
                "type": "marketing" if is_noise else "unusable" if too_short else "support_conversation",
                "relevant": relevant,
                "injection": False,  # detected separately by regex in classify_node
                "reason": (
                    "matched marketing/automated patterns" if is_noise
                    else "too short to analyse" if too_short
                    else "retained by keyword heuristic (no model available)"
                ),
            }
        )
    return HeuristicResult(
        data={"results": results},
        caveats=[
            "Records were filtered by keyword patterns rather than by a language model. "
            "Non-support content may remain and borderline records were kept."
        ],
    )


def heuristic_extract(texts: list[str]) -> HeuristicResult:
    """Derive issue phrase, product area, sentiment and severity by keyword."""
    results = []
    for index, text in enumerate(texts):
        area = next((name for name, pattern in _AREAS if pattern.search(text)), "unknown")

        # Issue phrase: the most distinctive words in the record, in original order.
        counts = Counter(_tokens(text))
        keywords = [w for w, _ in counts.most_common(4)]
        issue = " ".join(keywords) if keywords else "unspecified issue"

        blocked = bool(_BLOCKED.search(text))
        if _POSITIVE.search(text) and not blocked:
            sentiment = "positive"
        elif _FRUSTRATED.search(text) or blocked:
            sentiment = "frustrated"
        else:
            sentiment = "neutral"

        severity = "high" if (_HIGH_SEVERITY.search(text) or blocked) else "medium" if sentiment == "frustrated" else "low"

        results.append(
            {
                "index": index,
                "issue": issue,
                "product_area": area,
                "sentiment": sentiment,
                "blocked": blocked,
                "severity": severity,
            }
        )
    return HeuristicResult(
        data={"results": results},
        caveats=[
            "Issue descriptions are keyword summaries, not model-written phrases, and "
            "read as word lists rather than sentences."
        ],
    )


def heuristic_name_clusters(cluster_phrases: list[list[str]]) -> HeuristicResult:
    """Name each cluster from the words its members share most often."""
    themes = []
    for index, phrases in enumerate(cluster_phrases):
        counts = Counter()
        for phrase in phrases:
            counts.update(set(_tokens(phrase)))
        top = [w for w, _ in counts.most_common(3)]
        name = " ".join(top).title() if top else f"Unlabelled theme {index + 1}"
        themes.append(
            {
                "cluster": index,
                "name": name,
                "description": (
                    f"{len(phrases)} conversations sharing the terms "
                    f"{', '.join(top) if top else 'no distinctive terms'}. "
                    f"Grouped by text similarity; label derived from word frequency."
                ),
            }
        )
    return HeuristicResult(
        data={"themes": themes},
        caveats=[
            "Theme names are the most frequent shared terms in each cluster, not "
            "descriptions of the underlying issue. They read as keywords."
        ],
    )


# Table rows and headings in a prior digest, e.g. "| Export reliability | 38 |" or
# "Export reliability - 38 conversations" or "### Export reliability — 38 conversations".
_PRIOR_PATTERNS = [
    re.compile(r"^\s*\|\s*([^|]{3,80}?)\s*\|\s*(\d{1,6})\s*\|", re.M),
    re.compile(r"^#{1,4}\s*(.{3,80}?)\s*[—–-]\s*(\d{1,6})\s+conversations?", re.M | re.I),
    re.compile(r"^\s*[-*]?\s*(.{3,80}?)\s*[—–:-]\s*(\d{1,6})\s+conversations?", re.M | re.I),
]


def heuristic_parse_prior_digest(text: str) -> HeuristicResult:
    """Pull theme names and volumes out of a prior digest without a model.

    Only emits a theme when a number was actually found next to a name. A volume is
    never inferred, because a wrong prior number produces a confidently wrong growth
    figure — the exact class of claim this system is supposed to avoid.
    """
    seen: dict[str, int] = {}
    for pattern in _PRIOR_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1).strip(" |#*-—–:")
            if not name or name.lower() in {"theme", "name", "total", "volume"}:
                continue
            try:
                volume = int(match.group(2))
            except ValueError:
                continue
            seen.setdefault(name, volume)

    themes = [
        {"name": name, "volume": volume, "description": ""}
        for name, volume in seen.items()
    ]
    return HeuristicResult(
        data={"themes": themes},
        caveats=(
            [
                "The prior digest was parsed by pattern matching. Themes stated in prose "
                "rather than a table or heading were not detected, so the comparison may "
                "be incomplete."
            ]
            if themes
            else [
                "No theme/volume pairs could be pattern-matched out of the prior digest, "
                "so no comparison is included."
            ]
        ),
    )


def heuristic_summary(
    theme_rows: list[dict], total_conversations: int, quarter: str, comparison: bool
) -> HeuristicResult:
    """Factual executive summary assembled from counts, with no generated prose."""
    if not theme_rows:
        return HeuristicResult(
            data=f"No themes were identified from {total_conversations} conversations in {quarter}.",
        )

    top = theme_rows[0]
    share = round(float(top.get("volume_share", 0)) * 100)
    sentences = [
        f"{total_conversations} support conversations were analysed for {quarter}, "
        f"resolving into {len(theme_rows)} themes.",
        f"The highest-volume theme was {top['name']} with {top['volume_count']} "
        f"conversations ({share}% of the total).",
    ]

    if comparison:
        grew = [t for t in theme_rows if (t.get("growth_rate") or 0) > 0.15]
        if grew:
            fastest = max(grew, key=lambda t: t["growth_rate"])
            sentences.append(
                f"{len(grew)} theme(s) grew against the prior quarter, the fastest being "
                f"{fastest['name']} at {round(fastest['growth_rate'] * 100)}%."
            )
        else:
            sentences.append("No theme grew materially against the prior quarter.")
    else:
        sentences.append(
            "No prior-quarter digest was available, so no comparison is included."
        )

    return HeuristicResult(
        data=" ".join(sentences),
        caveats=[
            "The executive summary is assembled from counts rather than written, so it "
            "reports figures without interpreting them."
        ],
    )
