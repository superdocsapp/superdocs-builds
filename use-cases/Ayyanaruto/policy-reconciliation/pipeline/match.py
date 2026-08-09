"""Stage 3: SuperDocs multi-doc match + classify. Prompts live here."""

from __future__ import annotations

from .common import chat_json, client

MATCH_PROMPT = """Please compare the open handbook tabs for two merging companies (Northstar and Helios).
Search across the open documents. Return a JSON object only.

{roster}

Obligation index (ids and topics only — read the open tabs for wording; do not invent ids):
{obligation_index}

Pair files by subject matter, not by file name. For each pair recommend keep_a, keep_b, merge, or new.
- keep_a / keep_b: one section is the better complete base; leftover items go in coverage.
- merge: same subject, only number or threshold differences (receipt 50 vs 75, approval 200 vs 250, file-within 30 vs 45 days).
- new: opposite operating models (full remote vs three office days; accrued time off vs unlimited; required resignation notice vs none).

conflicts: only opposite operating models, with obligation ids.
coverage: every id above, disposition mapped, gap-A-only, or gap-B-only.

JSON shape:
{{
  "policies": [
    {{
      "id": "map_001",
      "title": "short title",
      "doc_a_filename": "file.docx or null",
      "doc_b_filename": "file.docx or null",
      "recommendation": "keep_a",
      "conflict": false,
      "evidence": "one or two sentences about the rules, not the file names",
      "obligation_ids_a": ["obl_a_001"],
      "obligation_ids_b": ["obl_b_001"]
    }}
  ],
  "conflicts": [
    {{
      "id": "conflict_001",
      "obligation_a_id": "obl_a_001",
      "obligation_b_id": "obl_b_004",
      "reason": "short reason"
    }}
  ],
  "coverage": [
    {{"obligation_id": "obl_a_001", "disposition": "mapped"}}
  ]
}}
"""

MATCH_RETRY_PROMPT = """Please return the handbook comparison as JSON only. A short answer is fine.

{roster}

Keys: policies, conflicts, coverage.
Pair Northstar files to Helios files by subject.
Recommend keep_a, keep_b, merge, or new.
Use merge for number differences; use new only for opposite operating models
(full remote vs office-days; accrued vs unlimited time off; required notice vs none).
Every id in this list must appear in coverage: {id_list}
"""


def roster_prompt(docs):
    lines = ["Open tabs:"]
    for estate, label in (("a", "Estate A (Northstar)"), ("b", "Estate B (Helios)")):
        lines.append(f"\n{label}:")
        for doc in docs:
            if doc["estate"] != estate:
                continue
            lines.append(f"- {doc['filename']}  document_id={doc.get('document_id')}")
    return "\n".join(lines)


def obligation_index(obligations):
    """Compact id roster for match chat — no quoted policy text (avoids SuperDocs safety filter)."""
    lines = ["id | estate | file | topic"]
    for obl in obligations:
        lines.append(
            f"{obl['id']} | {obl['estate']} | {obl.get('document_filename') or ''} | "
            f"{(obl.get('topic') or '').replace('|', '/')}"
        )
    return "\n".join(lines)


def _usable_match_payload(payload, job):
    reply = client.reply_text(job)
    if client.is_safety_refusal(reply):
        return None
    if isinstance(payload, dict) and (
        isinstance(payload.get("policies"), list) or isinstance(payload.get("coverage"), list)
    ):
        return payload
    return None


def match(docs, obligations, session_id):
    """Multi-doc SuperDocs match. Compact prompt first; one smaller SuperDocs retry. No local classify."""
    if not any(d.get("document_id") for d in docs):
        raise client.SuperDocsError("No document_ids; cannot match.")
    roster = roster_prompt(docs)
    index = obligation_index(obligations)
    ids = ", ".join(o["id"] for o in obligations)
    print(f"  match + classify in session {session_id}")
    payload, job = chat_json(
        MATCH_PROMPT.format(roster=roster, obligation_index=index),
        session_id,
    )
    usable = _usable_match_payload(payload, job)
    if usable is None:
        print("  SuperDocs match blocked or non-JSON; retrying with a smaller prompt")
        payload, job = chat_json(
            MATCH_RETRY_PROMPT.format(roster=roster, id_list=ids),
            session_id,
        )
        usable = _usable_match_payload(payload, job)
    if usable is not None:
        return usable, job.get("job_id")
    preview = (client.reply_text(job) or "")[:300]
    raise client.SuperDocsError(
        "SuperDocs match did not return JSON after retry "
        f"(safety filter or empty reply). preview: {preview!r}"
    )
