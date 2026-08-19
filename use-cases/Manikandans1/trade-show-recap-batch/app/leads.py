"""Lead record and CSV loader. Deliberately a plain dataclass with no
hidden state — every field a recap document could reference comes from
here, and nowhere else, which is what makes the no-cross-contamination
guarantee checkable: a recap document's content must be traceable to
exactly one Lead instance."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Lead:
    lead_id: str
    name: str
    company: str
    conversation_notes: str
    interest: str
    next_step: str

    @property
    def has_notes(self) -> bool:
        return bool(self.conversation_notes.strip())

    @property
    def has_interest(self) -> bool:
        return bool(self.interest.strip())

    @property
    def has_next_step(self) -> bool:
        return bool(self.next_step.strip())


def load_leads(csv_path: Path) -> list[Lead]:
    leads = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(
                Lead(
                    lead_id=row["lead_id"].strip(),
                    name=row["name"].strip(),
                    company=(row.get("company") or "").strip(),
                    conversation_notes=(row.get("conversation_notes") or "").strip(),
                    interest=(row.get("interest") or "").strip(),
                    next_step=(row.get("next_step") or "").strip(),
                )
            )
    return leads
