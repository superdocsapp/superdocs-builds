"""Stage 2: per-document SuperDocs extract. Prompt lives here."""

from __future__ import annotations

from .common import chat_json, client

EXTRACT_PROMPT = """Please read through this policy document and list the individual rules,
obligations, and requirements it contains. For each one, quote the exact
wording so nothing is paraphrased, and give it a short topic label.

Reply as a JSON object like this:
{"obligations": [{"text": "exact quote here", "topic": "short label here"}]}
"""

EXTRACT_RETRY_SUFFIX = """

Your previous reply was empty or not valid JSON. Reply with JSON only — no prose.
"""


def parse_extract_reply(payload, doc, counters):
    """Turn a per-document extract JSON into obligation records. Estate/filename come from ingest."""
    obligations = payload.get("obligations") if isinstance(payload, dict) else None
    if not isinstance(obligations, list):
        raise client.SuperDocsError(
            f"Extract reply for {doc.get('filename')} did not contain an obligations JSON array."
        )
    cleaned = []
    for item in obligations:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        estate = doc["estate"]
        counters[estate] = counters.get(estate, 0) + 1
        cleaned.append(
            {
                "id": f"obl_{estate}_{counters[estate]:03d}",
                "estate": estate,
                "document_id": doc.get("document_id"),
                "document_filename": doc.get("filename"),
                "topic": (item.get("topic") or "").strip() or None,
                "text": text,
            }
        )
    return cleaned


def extract(docs):
    """Per-document chat_async in the compare session. Skip a file after one retry if reply is not JSON."""
    cleaned = []
    job_ids = []
    counters = {"a": 0, "b": 0}
    for doc in docs:
        print(f"  extract [{doc['estate']}] {doc['filename']}")
        payload, job = chat_json(
            EXTRACT_PROMPT,
            doc["session_id"],
            document_id=doc.get("document_id"),
        )
        job_ids.append(job.get("job_id"))
        if not isinstance(payload, dict):
            print(f"  retry extract [{doc['estate']}] {doc['filename']} (empty or non-JSON reply)")
            payload, job = chat_json(
                EXTRACT_PROMPT + EXTRACT_RETRY_SUFFIX,
                doc["session_id"],
                document_id=doc.get("document_id"),
            )
            job_ids.append(job.get("job_id"))
        if not isinstance(payload, dict):
            preview = (client.reply_text(job) or "")[:200]
            print(
                f"  skip extract [{doc['estate']}] {doc['filename']}: "
                f"no JSON after retry. reply preview: {preview!r}"
            )
            continue
        try:
            cleaned.extend(parse_extract_reply(payload, doc, counters))
        except client.SuperDocsError as exc:
            print(f"  skip extract [{doc['estate']}] {doc['filename']}: {exc}")
    if not cleaned:
        raise client.SuperDocsError("Extract returned no usable obligations.")
    return cleaned, job_ids
