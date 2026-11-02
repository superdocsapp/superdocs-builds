"""AI coverage judgement.

Word overlap can only locate material; it cannot tell whether the material
is sufficient — a contract ending in 2027 satisfies every keyword of a
request that demands coverage through 2029. So the locator hands each
request and its found material to the model, and the model's reading —
verified by code — sets the coverage bucket.
"""
import json
import re

from engine.model import ChecklistRow, Coverage, Match, Request

# the chat API refuses messages over 100k characters; stay well under
MESSAGE_CHAR_LIMIT = 90_000
# progressively less material per request until the instruction fits
SHRINK_STEPS = [(2400, 5), (1600, 5), (1200, 4), (900, 3), (600, 2), (400, 1)]

JUDGE_RULES = (
    "You are reviewing the file for a response to a U.S. immigration "
    "Request for Evidence. For each numbered officer request below, judge "
    "whether the quoted petition material actually answers the officer's "
    "stated concern.\n"
    "Rules:\n"
    "1. Judge ONLY from the material quoted here. Do not assume any "
    "document exists beyond what is quoted.\n"
    "2. \"answered\" means the quoted material fully addresses the "
    "concern, including any dates, periods, places, and document types "
    "the officer names.\n"
    "3. \"partial\" means some material touches the concern but a real "
    "gap remains — name the gap.\n"
    "4. \"not_provided\" means nothing quoted addresses the concern.\n"
    "5. Reply with ONLY a JSON object, no other text, exactly this "
    "shape: {\"R1\": {\"coverage\": \"answered\", \"reason\": \"one "
    "sentence naming the evidence or the gap\"}, ...} with one entry per "
    "request.\n"
    "6. Do not edit or create any document. Reply in chat only."
)


def _flat(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + " [...]"


def build_judge_instruction(
    requests: list[Request], matches: dict[str, list[Match]]
) -> str:
    for excerpt_limit, per_request in SHRINK_STEPS:
        lines = [JUDGE_RULES]
        for request in requests:
            lines.append(f"--- Request {request.id}: {request.title}")
            # the officer's concern goes in whole; only the material quoted
            # under it shrinks when the instruction has to fit the message limit
            lines.append(f"Officer's concern: {' '.join(request.text.split())}")
            found = matches.get(request.id, [])[:per_request]
            if found:
                for match in found:
                    lines.append(
                        f"Petition material from {match.file} / \"{match.heading}\": "
                        f"\"{_flat(match.excerpt, excerpt_limit)}\""
                    )
            else:
                lines.append("Petition material: NONE found.")
        instruction = "\n".join(lines)
        if len(instruction) <= MESSAGE_CHAR_LIMIT:
            return instruction
    raise ValueError(
        "the judging instruction cannot fit the chat message limit even at "
        "minimum excerpt size — the notice has too many requests for one "
        "call; split the case or raise MESSAGE_CHAR_LIMIT after checking "
        "the API's current maximum"
    )


def parse_judge_reply(
    reply: str, requests: list[Request]
) -> dict[str, tuple[Coverage, str]]:
    found_json = re.search(r"\{.*\}", reply, re.DOTALL)
    if not found_json:
        raise ValueError(
            "the judge reply carried no JSON object — rerun; if it persists, "
            "raise model_tier in the run script"
        )
    try:
        data = json.loads(found_json.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"the judge reply's JSON does not parse ({e}) — rerun; if it "
            f"persists, raise model_tier in the run script"
        ) from e
    valid = {c.value for c in Coverage}
    verdicts = {}
    for request in requests:
        if request.id not in data:
            raise ValueError(
                f"the judge reply skipped {request.id} — every officer "
                f"request must be judged; rerun"
            )
        entry = data[request.id] or {}
        coverage = entry.get("coverage")
        if coverage not in valid:
            raise ValueError(
                f"the judge gave {request.id} the unknown coverage "
                f"'{coverage}' — expected one of {sorted(valid)}; rerun"
            )
        reason = (entry.get("reason") or "").strip() or "no reason given"
        verdicts[request.id] = (Coverage(coverage), reason)
    return verdicts


def judged_checklist(
    requests: list[Request],
    matches: dict[str, list[Match]],
    verdicts: dict[str, tuple[Coverage, str]],
) -> list[ChecklistRow]:
    rows = []
    for request in requests:
        coverage, reason = verdicts[request.id]
        found = matches.get(request.id, [])
        if coverage == Coverage.ANSWERED and not found:
            # the judge saw "NONE found" and still claimed an answer —
            # that is an invented answer, and code outranks it
            coverage = Coverage.NOT_PROVIDED
            reason = (
                "overridden: the judge claimed material but the locator "
                "found none — no petition material exists for this "
                "request; needs attorney confirmation"
            )
        rows.append(
            ChecklistRow(
                request_id=request.id,
                title=request.title,
                coverage=coverage,
                matches=found,
                reason=reason,
            )
        )
    return rows
