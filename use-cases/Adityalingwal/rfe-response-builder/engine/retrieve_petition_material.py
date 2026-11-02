import json
import re
from pathlib import Path

from engine.model import Match, Request, SourceSection

TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]+")
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
SUFFIXES = ("ions", "ing", "ion", "ers", "ies", "es", "ed", "er", "s")


def load_retrieval_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def split_into_sections(file_name: str, text: str) -> list[SourceSection]:
    headings = list(HEADING.finditer(text))
    if not headings:
        return [SourceSection(file=file_name, heading="(whole document)", text=text)]
    sections = []
    for i, m in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[m.end():end].strip()
        if body:
            sections.append(SourceSection(file=file_name, heading=m.group(2), text=body))
    return sections


def _stem(token: str) -> str:
    # "ies" maps to "y" so duty/duties and company/companies unify —
    # plain suffix-stripping leaves them as different stems.
    if token.endswith("ies") and len(token) - 3 >= 3:
        return token[:-3] + "y"
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _stems(text: str, stopwords: set[str]) -> set[str]:
    return {
        _stem(t)
        for t in TOKEN.findall(text.lower())
        if t not in stopwords and len(t) >= 3
    }


def retrieve(
    requests: list[Request],
    sections: list[SourceSection],
    config: dict,
) -> dict[str, list[Match]]:
    """Score every petition section against every request.

    Purely lexical and deterministic: the score is the fraction of the
    request's own content words the section covers. The model never sees
    this step, so a match can always be traced to the exact words that
    produced it.
    """
    stopwords = set(config["stopwords"])
    section_stems = [_stems(s.text + " " + s.heading, stopwords) for s in sections]

    matches: dict[str, list[Match]] = {}
    for request in requests:
        request_stems = _stems(request.title + " " + request.text, stopwords)
        total = len(request_stems) or 1
        scored = []
        per_file: dict[str, dict] = {}
        for section, stems in zip(sections, section_stems):
            shared = request_stems & stems
            score = len(shared) / total
            file_rollup = per_file.setdefault(
                section.file, {"stems": set(), "best": None, "best_score": -1.0}
            )
            file_rollup["stems"] |= shared
            if score > file_rollup["best_score"]:
                file_rollup["best"], file_rollup["best_score"] = section, score
            if score >= config["report_threshold"]:
                scored.append(
                    Match(
                        request_id=request.id,
                        file=section.file,
                        heading=section.heading,
                        excerpt=section.text,
                        score=round(score, 4),
                        shared_stems=len(shared),
                    )
                )
        # Evidence for one request may be spread across one document's
        # sections; the whole-file rollup keeps that from reading as weak.
        for file, rollup in per_file.items():
            file_score = len(rollup["stems"]) / total
            if file_score > rollup["best_score"] and file_score >= config["report_threshold"]:
                scored.append(
                    Match(
                        request_id=request.id,
                        file=file,
                        heading="(across sections)",
                        excerpt=rollup["best"].text,
                        score=round(file_score, 4),
                        shared_stems=len(rollup["stems"]),
                    )
                )
        scored.sort(key=lambda m: m.score, reverse=True)
        matches[request.id] = scored[: config["max_matches_per_request"]]
    return matches
