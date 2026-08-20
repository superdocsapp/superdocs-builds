"""Google Chat card builders (cardsV2). Pure functions → easy to unit-test and
they render on desktop and mobile Chat.

Docs: a Chat app replies to an event with JSON containing ``cardsV2``. Buttons
carry an ``action`` whose ``function`` + ``parameters`` come back as a
CARD_CLICKED event we dispatch on. Responding to a click with
``actionResponse.type = UPDATE_MESSAGE`` updates the same card in place, which is
how per-item approve/reject ticks land without spamming the thread with new cards.
"""

from __future__ import annotations

_ICON = {"approved": "✅", "rejected": "❌", None: "⬜️"}


def _card(card_id: str, header: dict, sections: list[dict]) -> dict:
    return {"cardsV2": [{"cardId": card_id, "card": {"header": header, "sections": sections}}]}


def updated(response: dict) -> dict:
    """Wrap a card response so a CARD_CLICKED reply updates the clicked message
    in place instead of posting a new one."""
    return {"actionResponse": {"type": "UPDATE_MESSAGE"}, **response}


def summary_card(*, doc_title: str, doc_link: str | None, request: str, produced: str,
                 reference: str | None = None) -> dict:
    """Posted in-thread after the app drafts/edits a document."""
    widgets = [
        {"decoratedText": {"topLabel": "Request", "text": request, "wrapText": True}},
        {"decoratedText": {"topLabel": "Produced", "text": produced, "wrapText": True}},
    ]
    if reference:
        widgets.insert(1, {"decoratedText": {"topLabel": "Referenced", "text": reference,
                                             "wrapText": True}})
    sections = [{"widgets": widgets}]
    if doc_link:
        sections.append({"widgets": [{"buttonList": {"buttons": [
            {"text": "Download current draft", "onClick": {"openLink": {"url": doc_link}}},
        ]}}]})
    return _card("summary", {"title": "SuperDocs", "subtitle": doc_title}, sections)


def approval_card(*, session_id: str, job_id: str, doc_title: str, changes: list) -> dict:
    """One reviewable card: each proposed change with its own Approve / Reject
    buttons (item-by-item), plus Approve all / Reject all shortcuts and an
    Apply decisions gate. ``changes`` items expose change_id/operation/summary and
    an optional ``decision`` ("approved"|"rejected"|None)."""
    base = [
        {"key": "session_id", "value": session_id},
        {"key": "job_id", "value": job_id},
    ]

    def _btn(text, fn, extra=None):
        params = base + ([{"key": "change_id", "value": extra}] if extra else [])
        return {"text": text, "onClick": {"action": {"function": fn, "parameters": params}}}

    sections = []
    for c in changes:
        decision = getattr(c, "decision", None)
        sections.append({"widgets": [
            {"decoratedText": {
                "topLabel": f"{_ICON.get(decision, '⬜️')} {c.operation.upper()} · {c.change_id[:8]}",
                "text": (c.summary or "(no explanation)"),
                "wrapText": True,
            }},
            {"buttonList": {"buttons": [
                _btn("✅ Approve", "approve_one", c.change_id),
                _btn("❌ Reject", "reject_one", c.change_id),
            ]}},
        ]})

    sections.append({"widgets": [{"buttonList": {"buttons": [
        _btn("Apply decisions", "apply_decisions"),
        _btn("Approve all", "approve_all"),
        _btn("Reject all", "reject_all"),
    ]}}]})

    n = len(changes)
    return _card("approval", {"title": "Review proposed changes",
                              "subtitle": f"{doc_title} — {n} change(s)"}, sections)


def result_card(*, doc_title: str, applied: int, rejected: int,
                download_url: str | None, filename: str | None) -> dict:
    buttons = []
    if download_url:
        buttons.append({"text": f"Download {filename or 'document'}",
                        "onClick": {"openLink": {"url": download_url}}})
    sections = [{"widgets": [{"decoratedText": {
        "text": f"✅ Applied {applied}, rejected {rejected}.", "wrapText": True}}]}]
    if buttons:
        sections.append({"widgets": [{"buttonList": {"buttons": buttons}}]})
    return _card("result", {"title": "SuperDocs", "subtitle": doc_title}, sections)


def digest_card(*, produced: list[dict], pending: list[dict]) -> dict:
    def rows(items, empty):
        if not items:
            return [{"decoratedText": {"text": empty}}]
        return [{"decoratedText": {"topLabel": i["title"], "text": i["state"], "wrapText": True}}
                for i in items]

    return _card(
        "digest",
        {"title": "SuperDocs — daily digest", "subtitle": "what this space produced"},
        [
            {"header": f"Produced ({len(produced)})", "widgets": rows(produced, "Nothing yet today.")},
            {"header": f"Waiting on someone ({len(pending)})",
             "widgets": rows(pending, "Nothing pending — nice.")},
        ],
    )


def text(message: str) -> dict:
    return {"text": message}
