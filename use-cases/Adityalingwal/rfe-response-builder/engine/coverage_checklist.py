from engine.model import ChecklistRow, Coverage, Match, Request


def build_checklist(
    requests: list[Request],
    matches: dict[str, list[Match]],
    config: dict,
) -> list[ChecklistRow]:
    """One row per request in the notice — never fewer.

    A request with no petition material stays on the checklist marked
    not_provided; dropping it would be exactly the silent gap this tool
    exists to prevent.
    """
    strong = config["strong_threshold"]
    weak = config["weak_threshold"]
    min_shared = config["min_shared_stems_for_answered"]
    rows = []
    for request in requests:
        found = matches.get(request.id, [])
        best = found[0].score if found else 0.0
        # A short request can overlap a section on a handful of generic
        # words and still score a high fraction — "answered" therefore also
        # demands an absolute number of shared content words.
        solid = next(
            (m for m in found if m.score >= strong and m.shared_stems >= min_shared),
            None,
        )
        if solid:
            coverage = Coverage.ANSWERED
            reason = f"petition material found in {solid.file} ('{solid.heading}')"
        elif best >= weak:
            coverage = Coverage.PARTIAL
            reason = (
                f"only weak petition material found (best: {found[0].file}, "
                f"'{found[0].heading}') — new evidence needed"
            )
        else:
            coverage = Coverage.NOT_PROVIDED
            reason = "no petition material addresses this request — needs attorney confirmation"
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
