"""Assemble the credit documentation packet through SuperDocs.

The flow is the four-call contract the task document names as the minimum:
upload, chat, approve, export -- applied across a multi-document bundle.

Nothing is written to disk that a human has not approved. Every figure that
reaches a document was computed in calc.py first.
"""

from __future__ import annotations

import hashlib
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


def _document_id_from(changes: list[client.Change]) -> str | None:
    """The id of the document a batch of changes belongs to.

    A create returns it on the change itself -- observed live as
    `doc_created_...` on the seed change. Captured here because every later
    targeted instruction and every per-document export needs it: without it
    the API falls back to the session's own document and a multi-document
    bundle silently becomes one document under several names.
    """
    for change in changes:
        if change.document_id:
            return change.document_id
    return None


def _marked_missing(html: str, filename: str) -> bool:
    """Is this filename described as outstanding where the index lists it?

    Read within the row or line that names the file, so wording elsewhere in
    the document cannot vouch for an item listed as though it were in hand.
    """
    words = ("outstanding", "missing", "not present", "not received",
             "awaited", "pending", "unavailable")
    for line in html.splitlines():
        if filename in line:
            return any(w in line.lower() for w in words)
    # The filename spans lines; fall back to the surrounding window.
    at = html.find(filename)
    if at == -1:
        return False
    window = html[max(0, at - 200): at + 200].lower()
    return any(w in window for w in words)


def _states_total(html: str, total: int) -> bool:
    """Does the cover give this figure as its claimed total?

    Anchored to the label so an incidental number -- a floor area, a date, a
    certificate id -- cannot stand in for the total the packet computed.
    """
    # Allow the markup between label and figure -- "</td><td>", "|", ":" --
    # but no other digits, so the figure found is the one the label introduces.
    pattern = re.compile(
        r"points\s+claimed\b[^0-9]{0,60}?\b" + str(total) + r"\b",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(pattern.search(html))


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
        # Set when a gate is left undecided: the session will refuse the next
        # instruction with a 409 until a person decides the staged changes.
        self.awaiting_review = False
        # Honesty counters: how many instructions genuinely waited for a human,
        # and which ones the API applied without asking.
        self.gated = 0
        self.ungated: list[str] = []
        # Sections that produced no content even after a retry. Surfaced in
        # verify() rather than leaving a hole in the packet.
        self.empty_sections: list[str] = []
        # The responses from the most recent propagation, one per document
        # edited, kept so the caller can read their job ids when approving.
        # A status change now touches two documents, so this is a list.
        self.last_propagation: list[dict] = []

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

    def _run_section(self, label: str, instruction: str, *, approve: bool,
                     key: str) -> list[client.Change]:
        """Send one instruction and handle its gate. Returns its changes.

        Retries once when a section produces nothing at all, because a silently
        empty section is how a whole calculation went missing on an early run.
        """
        response = self.sd.chat_async(instruction, self.session_id, stage=label)
        changes = self.sd.changes_from(response)

        if response.get("status") != "awaiting_approval" and not changes:
            response = self.sd.chat_async(
                instruction, self.session_id, stage=f"{label}:retry"
            )
            changes = self.sd.changes_from(response)

        if response.get("status") == "awaiting_approval":
            self.gated += 1
            if approve and not changes:
                # The gate engaged but no changes parsed out of the payload.
                # Approving an empty decision list sends "approved": false and
                # silently rejects the section, so record it instead of
                # discarding work under the appearance of approving it.
                self.empty_sections.append(key)
            elif approve:
                job_id = response.get("job_id")
                self.sd.approve(
                    self.session_id,
                    [{"change_id": c.change_id, "approved": True} for c in changes],
                    job_id=job_id,
                )
                # Approving records the decision and returns; the edit is then
                # applied asynchronously and the job runs on to `completed`.
                # Sending the next instruction during that window earns a 409
                # and the section is lost, so wait on this job specifically --
                # the session-wide jobs listing comes back empty and cannot be
                # used to tell whether the edit has landed.
                if job_id:
                    self.sd.wait_for_job(
                        job_id, stage="settle", until=("completed", "failed"),
                    )
                else:
                    self.sd.wait_until_idle(self.session_id)
            else:
                self.pending[key] = Pending(
                    job_id=response.get("job_id") or "",
                    session_id=self.session_id,
                    changes=changes,
                )
                # A session holds one undecided batch at a time: sending the
                # next instruction while this one waits earns a 409
                # session_busy. Signal the caller to stop building here and
                # let a person decide before the next section is proposed.
                self.awaiting_review = True
        elif changes:
            # Content landed without the gate engaging. Recorded, not glossed
            # over. See docs/BUGS.md #1.
            self.ungated.append(key)
        else:
            self.empty_sections.append(key)

        return changes

    def build_scorecard(self, *, approve: bool = False) -> Document:
        """Build the cover sheet, one gated section at a time."""
        seed = self.sd.chat(
            prompts.scorecard_seed(self.scorecard), self.session_id, stage="seed:scorecard"
        )
        # The create carries the new document's id; hold it so later edits and
        # the export can be aimed at this document rather than the session.
        document_id = _document_id_from(self.sd.changes_from(seed))

        parts: list[str] = []
        for label, instruction in prompts.scorecard_sections(self.scorecard):
            changes = self._run_section(
                f"{label}:scorecard", instruction, approve=approve,
                key=f"scorecard:{label}",
            )
            parts.extend(c.new_html for c in changes if c.new_html)
            document_id = document_id or _document_id_from(changes)

        doc = Document(
            key="scorecard",
            title="Scorecard cover",
            html="\n".join(parts),
            session_id=self.session_id,
            document_id=document_id,
        )
        self.documents["scorecard"] = doc
        return doc

    def build_narrative(self, credit: registry.Credit, *,
                        approve: bool = False) -> Document:
        """Build one credit's section, one gated instruction at a time.

        Each section is proposed as an addition and waits for a human decision.
        With approve=True the caller is accepting every section as it comes,
        which is what the non-interactive scripted run does; the review CLI
        passes approve=False and decides per change.
        """
        seed = self.sd.chat(
            prompts.narrative_seed(credit, self.scorecard.project),
            self.session_id,
            stage=f"seed:{credit.id}",
        )
        document_id = _document_id_from(self.sd.changes_from(seed))

        html_parts: list[str] = []
        for label, instruction in prompts.narrative_sections(credit, self.scorecard.project):
            changes = self._run_section(
                f"{label}:{credit.id}", instruction, approve=approve,
                key=f"{credit.id}:{label}",
            )
            html_parts.extend(c.new_html for c in changes if c.new_html)
            document_id = document_id or _document_id_from(changes)

        doc = Document(
            key=credit.id,
            title=f"{credit.id} {credit.name}",
            html="\n".join(html_parts),
            session_id=self.session_id,
            document_id=document_id,
        )
        self.documents[credit.id] = doc
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
        credit = after.credit(credit_id)

        # Two targeted instructions, one per document, rather than one
        # instruction against the whole session: the scorecard cover and the
        # credit narrative say different things about a status change, and a
        # single edit aimed at both rewrites more than it should.
        targets = [
            ("scorecard", prompts.propagate_scorecard(credit, after, new_status)),
            (credit_id, prompts.propagate_narrative(credit, old_status, new_status)),
        ]

        responses, changes = [], []
        for doc_key, instruction in targets:
            doc = self.documents.get(doc_key)
            if doc is None:
                continue
            extra = {"document_id": doc.document_id} if doc.document_id else {}
            response = self.sd.chat_async(
                instruction,
                self.session_id,
                stage=f"propagate:{doc_key}",
                **extra,
            )
            responses.append(response)
            changes.extend(self.sd.changes_from(response))

        self.last_propagation = responses
        return after, changes

    def apply(self, scorecard: registry.Scorecard, decisions: list[dict],
              *, job_id: str | None = None) -> dict | list[dict]:
        """Commit the approved changes. Rejected ones are left behind.

        The scorecard is only advanced if at least one change was approved, so
        a wholly rejected batch leaves the packet exactly as it was.

        A status change proposes changes across two documents and so produces
        two jobs. The approve endpoint decides one job at a time, so decisions
        are grouped by the job that proposed them and sent per job; an explicit
        job_id overrides the grouping for the single-job case.
        """
        if job_id is None and any(d.get("job_id") for d in decisions):
            by_job: dict[str, list[dict]] = {}
            for decision in decisions:
                by_job.setdefault(decision.get("job_id") or "", []).append(decision)
            results = [
                self.sd.approve(self.session_id, group, job_id=jid or None)
                for jid, group in by_job.items()
            ]
        else:
            results = [self.sd.approve(self.session_id, decisions, job_id=job_id)]

        if any(d.get("approved") for d in decisions):
            self.scorecard = scorecard
        return results[0] if len(results) == 1 else results

    # --------------------------------------------------------------- export
    def export(self, out_dir: Path, fmt: str = "docx") -> list[Path]:
        """Write each document to its own file.

        Each export is selected by document_id. Without one the endpoint
        returns the session's own document, so every file would receive
        identical bytes under a different name -- and pay an operation for the
        privilege. Duplicates are reported rather than written quietly.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        seen: dict[bytes, str] = {}
        self.export_duplicates: list[str] = []

        for doc in self.documents.values():
            data = self.sd.export(
                self.session_id, fmt,
                document_id=doc.document_id, filename=doc.key,
            )
            digest = hashlib.sha256(data).digest()
            if digest in seen:
                self.export_duplicates.append(
                    f"{doc.key}: identical bytes to {seen[digest]} -- "
                    "the export was not selected by document"
                )
            else:
                seen[digest] = doc.key
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
        # A missing item has to appear in the index AND be described as missing;
        # the failure that matters is one listed as though it were in hand, so
        # the check reads the text around the filename rather than only asking
        # whether the filename occurs.
        for credit in self.scorecard.credits:
            doc = self.documents.get(credit.id)
            if not doc:
                continue
            for item in credit.evidence:
                if item.present:
                    continue
                if item.file not in doc.html:
                    problems.append(
                        f"{credit.id}: evidence index omits missing item {item.file}"
                    )
                elif not _marked_missing(doc.html, item.file):
                    problems.append(
                        f"{credit.id}: evidence index lists missing item "
                        f"{item.file} without marking it outstanding"
                    )

        # A document with no id cannot be targeted or exported on its own, so
        # the bundle would quietly collapse into one document under several
        # names. Reported here rather than discovered in the exported files.
        for doc in self.documents.values():
            if not doc.document_id:
                problems.append(
                    f"{doc.key}: no document id was captured, so edits and "
                    "exports would fall back to the session's own document"
                )

        # Criterion 3: the cover must carry the computed total, not a guess.
        # Matched against the labelled figure, not the bare number: a cover
        # carrying "214,000 sf" or a 2013 date would satisfy a substring test
        # for "13" while claiming any total at all.
        cover = self.documents.get("scorecard")
        if cover and not _states_total(cover.html, self.scorecard.points_awarded):
            problems.append(
                f"scorecard: computed total {self.scorecard.points_awarded} "
                "does not appear in the cover against its label"
            )
        return problems
