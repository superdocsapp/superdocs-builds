"""
Deterministic rendering of the owned section's content from source data.
Same input always produces the same instruction text, which is what makes
the stopping rule possible: if the source hasn't changed, there is nothing
new to say, so the agent says nothing and spends nothing.
"""

import hashlib
import json

OWNED_SECTION_HEADING = "[AGENT-MAINTAINED] Live Service Status -- do not edit manually"

_STATUS_LABEL = {"operational": "Operational", "degraded": "Degraded", "down": "Down"}


def source_hash(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def render_section_instruction(data: dict) -> str:
    """The natural-language instruction body describing exactly what the
    owned section's table should contain -- deterministic given the same
    source data, so re-running against unchanged data would (if it ever
    ran, which the stopping rule prevents) produce an identical request.

    The "last synced" timestamp is folded INTO the table (a final row
    spanning all three columns) rather than a separate paragraph after it.
    Found the hard way (see PROGRESS.md): with the timestamp as its own
    paragraph, an update instruction worded as "replace the table AND the
    last-synced line" got interpreted as "add a new last-synced paragraph"
    rather than "replace the existing one" -- leaving both the old and new
    paragraph in the document, one of them not even chunk-addressable. One
    chunk (the table) with everything dynamic inside it removes the
    insert-vs-replace ambiguity entirely: there is only ever one thing to
    replace, and "replace this whole table with an updated table" is not
    ambiguous the way "also update that line somewhere below" turned out
    to be."""
    rows = []
    for svc in data["services"]:
        label = _STATUS_LABEL.get(svc["status"], svc["status"])
        rows.append(f"{svc['name']} | {label} | {svc['latency_ms']}ms")
    table_desc = "\n".join(rows)
    return (
        f"A table with columns Service, Status, Latency, containing exactly these data rows "
        f"(one row per line, pipe-separated -- Service | Status | Latency):\n{table_desc}\n\n"
        f"Then one final row, its single cell spanning all three columns, containing exactly: "
        f"\"Last synced: {data['generated_at']}\". The table has no separate caption or "
        f"paragraph outside it -- the last-synced text is the table's last row, nothing else."
    )
