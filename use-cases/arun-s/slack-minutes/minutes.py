"""Turn a Slack thread into structured meeting minutes, then a branded exported doc.

A flow that starts in another tool (Slack) and ends in an edited, exported document:
  Slack thread --> {attendees, decisions, action items, discussion} --> HTML --> SuperDocs --> .docx

Extraction is keyword-cued and deterministic (keyless): 'decided/agreed' -> a decision;
'action/todo/will/by <date>' or an @mention with an owner -> an action item.
"""
from __future__ import annotations
import re

DECISION = re.compile(r"\b(decided|decision|we'll go with|agreed|approved|conclusion)\b", re.I)
ACTION = re.compile(r"\b(action|todo|to-do|will|to be done|follow up|by (mon|tue|wed|thu|fri|next|eod|tomorrow))\b", re.I)
MENTION = re.compile(r"@([A-Za-z0-9._-]+)")


def structure(messages: list[dict]) -> dict:
    attendees, decisions, actions, discussion = [], [], [], []
    for m in messages:
        u = m.get("user", "?")
        if u not in attendees:
            attendees.append(u)
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if DECISION.search(text):
            decisions.append({"by": u, "text": text})
        elif ACTION.search(text):
            owner = MENTION.search(text)
            actions.append({"owner": owner.group(1) if owner else u, "text": text})
        else:
            discussion.append({"by": u, "text": text})
    return {"attendees": attendees, "decisions": decisions, "actions": actions, "discussion": discussion}


def _ul(items: list[str]) -> str:
    if not items:
        return "<p>None.</p>"
    return "<ul>" + "".join("<li>" + i + "</li>" for i in items) + "</ul>"


def minutes_html(structured: dict, title: str = "Meeting minutes") -> str:
    attendees = ", ".join(structured["attendees"]) or "—"
    decisions = _ul([d["text"] + " <em>(" + d["by"] + ")</em>" for d in structured["decisions"]])
    actions = _ul(["<b>" + a["owner"] + "</b>: " + a["text"] for a in structured["actions"]])
    discussion = _ul([d["text"] + " <em>(" + d["by"] + ")</em>" for d in structured["discussion"]])
    return (f"<h1>{title}</h1><p><b>Attendees:</b> {attendees}</p>"
            f"<h2>Decisions</h2>{decisions}"
            f"<h2>Action items</h2>{actions}"
            f"<h2>Discussion</h2>{discussion}")


def export_minutes(slack, superdocs, channel: str, thread_ts: str, title: str = "Meeting minutes",
                   session_id: str = "slack-minutes") -> dict:
    structured = structure(slack.thread(channel, thread_ts))
    html = minutes_html(structured, title)
    superdocs.send_document(html, session_id, "Format as branded meeting minutes with headings.")
    return {"structured": structured, "html": html, "docx": superdocs.export(session_id, "docx")}
