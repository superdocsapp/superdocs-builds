"""Assemble the credit documentation packet through SuperDocs.

The flow is the four-call contract the task document names as the minimum:
upload, chat, approve, export -- applied across a multi-document bundle.

Nothing is written to disk that a human has not approved. Every figure that
reaches a document was computed in calc.py first.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import client
import prompts
import registry
import sources

# A run's operation ceiling. The account has a monthly allowance and the task
# document advises budgeting deliberately rather than discovering the limit on
# day nine; this stops a bug from draining it.
DEFAULT_BUDGET = 40

GAP_MARKER = "[GAP:"


@dataclass
class Pending:
    """Changes proposed and waiting on a human decision."""

    job_id: str
    session_id: str
    changes: list[client.Change]

    def decisions(self, approved: set[str] | None = None) -> list[dict]:
        """Build the per-change decision list.

        `approved` names the chunk ids to accept; everything else is rejected.
        Passing None approves all of them. Decisions are always per chunk, so
        rejecting one never discards the rest.
        """
        # Decisions are keyed by change_id: the documented chunk_id form
        # returns a 500 from the API. See docs/BUGS.md #3.
        return [
            {
                "change_id": c.change_id,
                "approved": approved is None or c.chunk_id in approved,
            }
            for c in self.changes
        ]


@dataclass
class Document:
    """One document in the bundle, as it stands after the last approved edit."""

    key: str
    title: str
    html: str
    session_id: str
    document_id: str | None = None

    @property
    def gaps(self) -> list[str]:
        """Passages the model flagged as unsupported by the requirement text."""
        return re.findall(r"\[GAP:[^\]]*\]", self.html)

    @property
    def placeholders(self) -> list[str]:
        """Unfilled template text that must never reach a submission."""
        return re.findall(r"(?i)please fill[^<\n.]{0,60}", self.html)


class Packet:
    def __init__(self, scorecard: registry.Scorecard, sd: client.SuperDocs | None = None,
                 *, session_prefix: str | None = None, budget: int = DEFAULT_BUDGET):
        self.scorecard = scorecard
        self.sd = sd or client.SuperDocs(budget=budget)
        self.session_id = session_prefix or f"packet-{uuid.uuid4().hex[:8]}"
        self.documents: dict[str, Document] = {}
        self.unattached: list[str] = []
        self.pending: dict[str, Pending] = {}
        # Honesty counters: how many instructions genuinely waited for a human,
        # and which ones the API applied without asking.
        self.gated = 0
        self.ungated: list[str] = []
        # Sections that produced no content even after a retry. Surfaced in
        # verify() rather than leaving a hole in the packet.
        self.empty_sections: list[str] = []

    # ------------------------------------------------------------- assembly
    def attach_sources(self, credit: registry.Credit) -> None:
        """Upload the requirement text and the credit's present evidence.

        The requirement goes up as a file rather than being pasted into the
        instruction, so the narrative is written against an attached source --
        which is what the card grades.
        """
        cache = Path(".sources")
        self.sd.upload(
            sources.prepare(Path(credit.requirement_file), cache),
            self.session_id, open_mode="background",
        )
        for item in credit.evidence:
            if not item.present:
                continue
            try:
                prepared = sources.prepare(Path(item.location), cache)
            except sources.UnsupportedSource as exc:
                # Surfaced, not swallowed: the evidence index must still show
                # this item, and the run should say what it could not attach.
                self.unattached.append(f"{credit.id}: {exc}")
                continue
            self.sd.upload(prepared, self.session_id, open_mode="background")

    def build_narrative(self, credit: registry.Credit, *,
                        approve: bool = False) -> Document:
        """Build one credit's section, one gated instruction at a time.

        Each section is proposed as an addition and waits for a human decision.
        With approve=True the caller is accepting every section as it comes,
        which is what the non-interactive scripted run does; the review CLI
        passes approve=False and decides per change.
        """
        self.sd.chat(
            prompts.narrative_seed(credit, self.scorecard.project),
            self.session_id,
            stage=f"seed:{credit.id}",
        )

        html_parts: list[str] = []
        for label, instruction in prompts.narrative_sections(credit, self.scorecard.project):
            response = self.sd.chat_async(
                instruction, self.session_id, stage=f"{label}:{credit.id}"
            )
            changes = self.sd.changes_from(response)
            job_id = response.get("job_id")

            if response.get("status") == "awaiting_approval":
                self.gated += 1
                if approve:
                    self.sd.approve(
                        self.session_id,
                        [{"change_id": c.change_id, "approved": True} for c in changes],
                        job_id=job_id,
                    )
                    # Approving returns before the job finishes; the next
                    # instruction would otherwise get a 409 session_busy.
                    self.sd.wait_until_idle(self.session_id)
                else:
                    self.pending[f"{credit.id}:{label}"] = Pending(
                        job_id=job_id or "", session_id=self.session_id, changes=changes
                    )
            elif response.get("status") == "completed" and changes:
                # The gate did not engage but content was produced. Recorded
                # rather than passed off as reviewed. See docs/BUGS.md #1.
                self.ungated.append(f"{credit.id}:{label}")
            else:
                # No changes and no gate: the section produced nothing at all.
                # Retried once, because a silently empty section is how the
                # calculation went missing on the first real run.
                retry = self.sd.chat_async(
                    instruction, self.session_id, stage=f"{label}:{credit.id}:retry"
                )
                changes = self.sd.changes_from(retry)
                if retry.get("status") == "awaiting_approval":
                    self.gated += 1
                    if approve:
                        self.sd.approve(
                            self.session_id,
                            [{"change_id": c.change_id, "approved": True} for c in changes],
                            job_id=retry.get("job_id"),
                        )
                        self.sd.wait_until_idle(self.session_id)
                if not changes:
                    self.empty_sections.append(f"{credit.id}:{label}")

            html_parts.extend(c.new_html for c in changes if c.new_html)

        doc = Document(
            key=credit.id,
            title=f"{credit.id} {credit.name}",
            html="\n".join(html_parts),
            session_id=self.session_id,
        )
        self.documents[credit.id] = doc
        return doc

    def build_scorecard(self) -> Document:
        response = self.sd.chat(
            prompts.scorecard(self.scorecard),
            self.session_id,
            stage="scorecard",
        )
        doc = Document(
            key="scorecard",
            title="Scorecard cover",
            html=self._html_from(response),
            session_id=self.session_id,
        )
        self.documents["scorecard"] = doc
        return doc

    def build(self, credit_ids: list[str] | None = None) -> dict[str, Document]:
        """Build the whole bundle: a narrative per credit, then the cover."""
        credits = [
            c for c in self.scorecard.credits
            if credit_ids is None or c.id in credit_ids
        ]
        for credit in credits:
            self.attach_sources(credit)
            self.build_narrative(credit)
        self.build_scorecard()
        return self.documents

    # ---------------------------------------------------------- propagation
    def change_status(self, credit_id: str, new_status: str) -> tuple[registry.Scorecard, list[client.Change]]:
        """Propose the edits a status change requires, across both documents.

        Returns the recomputed scorecard and the proposed changes. Nothing is
        applied here -- the changes go to a human first.
        """
        before = self.scorecard
        old_status = before.credit(credit_id).status
        after = registry.set_status(before, credit_id, new_status)

        response = self.sd.chat(
            prompts.propagate(after.credit(credit_id), after, old_status, new_status),
            self.session_id,
            stage=f"propagate:{credit_id}",
        )
        return after, self.sd.changes_from(response)

    def apply(self, scorecard: registry.Scorecard, decisions: list[dict],
              *, job_id: str | None = None) -> dict:
        """Commit the approved changes. Rejected ones are left behind.

        The scorecard is only advanced if at least one change was approved, so
        a wholly rejected batch leaves the packet exactly as it was.
        """
        result = self.sd.approve(self.session_id, decisions, job_id=job_id)
        if any(d.get("approved") for d in decisions):
            self.scorecard = scorecard
        return result

    # --------------------------------------------------------------- export
    def export(self, out_dir: Path, fmt: str = "docx") -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for doc in self.documents.values():
            data = self.sd.export(self.session_id, fmt, filename=doc.key)
            path = out_dir / f"{doc.key}.{fmt}"
            path.write_bytes(data)
            written.append(path)
        return written

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _html_from(response: dict) -> str:
        """The document as it now stands.

        updated_html is null on a full-document create, so fall back to the
        html carried on the change objects themselves before giving up and
        returning the assistant's prose.
        """
        changes = response.get("document_changes") or {}
        if isinstance(changes, dict):
            if changes.get("updated_html"):
                return changes["updated_html"]
            fragments = [
                c.get("new_html", "")
                for c in (changes.get("changes") or [])
                if isinstance(c, dict) and c.get("new_html")
            ]
            if fragments:
                return "\n".join(fragments)
        return response.get("response") or response.get("text", "")

    def verify(self) -> list[str]:
        """Check the built bundle against the card's three criteria.

        Returns the problems found. An empty list is the honest report of no
        findings; a non-empty one is surfaced rather than silently repaired.
        """
        problems = []

        for section in self.empty_sections:
            problems.append(f"{section}: section produced no content")
        for section in self.ungated:
            problems.append(f"{section}: content landed without human review")

        for doc in self.documents.values():
            for gap in doc.gaps:
                problems.append(f"{doc.key}: unsupported claim flagged -- {gap}")
            for placeholder in doc.placeholders:
                problems.append(
                    f"{doc.key}: unfilled placeholder left in document -- {placeholder!r}"
                )

        # Criterion 2: the index must not claim a missing document is present.
        for credit in self.scorecard.credits:
            doc = self.documents.get(credit.id)
            if not doc:
                continue
            for item in credit.evidence:
                if not item.present and item.file not in doc.html:
                    problems.append(
                        f"{credit.id}: evidence index omits missing item {item.file}"
                    )

        # Criterion 3: the cover must carry the computed total, not a guess.
        cover = self.documents.get("scorecard")
        if cover and str(self.scorecard.points_awarded) not in cover.html:
            problems.append(
                f"scorecard: computed total {self.scorecard.points_awarded} "
                "does not appear in the cover"
            )
        return problems
