"""One way in, shared by the CLI and the MCP server.

Both front ends need the same four things — a registry, a state file, two fact
tables and a client — and the rules about which baseline to use and when a key
is required are the kind of thing that drifts apart if it is written twice. So
it is written once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from docsync.facts import (
    DirectoryTree,
    FactTable,
    GitRevisionTree,
    SourceError,
    WorkingTree,
    is_git_repo,
    read_facts,
    table_from_snapshot,
)
from docsync.plan import AuditFinding, ChangePlan, audit, build_plan
from docsync.registry import Registry, RegistryError
from docsync.state import State
from docsync.superdocs import BASE_URL, Ledger, SuperDocs, load_env


@dataclass
class Workspace:
    registry: Registry
    state: State

    @classmethod
    def open(cls, path: Path | str = ".") -> Workspace:
        registry = Registry.load(path)
        state = State.load(registry.root, session_id=registry.session_id)
        if not state.session_id:
            state.session_id = registry.session_id
        return cls(registry=registry, state=state)

    @property
    def root(self) -> Path:
        return self.registry.root

    @property
    def session_id(self) -> str:
        return self.state.session_id or self.registry.session_id

    # -- fact tables -------------------------------------------------------

    def facts_now(self) -> FactTable:
        return read_facts(self.registry, WorkingTree(self.root))

    def facts_before(self, *, base: str = "", base_dir: str = "") -> FactTable:
        """The baseline, from whichever of the three sources was asked for.

        The default — the recorded snapshot — is chosen over "git HEAD" on
        purpose. ``HEAD`` answers "what have I not committed yet", which goes
        empty the moment you commit and would make the tool useless in exactly
        the situation it is for: a branch of six commits about to become a pull
        request. The snapshot answers "what has moved since the docs were last
        brought into step", which stays true across commits.
        """
        if base and base_dir:
            raise RegistryError("--base and --base-dir do the same job; pass one of them")
        if base:
            return read_facts(self.registry, GitRevisionTree(self.root, base))
        if base_dir:
            return read_facts(self.registry, DirectoryTree(Path(base_dir).resolve()))
        if self.state.facts:
            return table_from_snapshot(self.registry, self.state.facts)
        raise SourceError(
            "there is no baseline to compare against: no snapshot has been recorded "
            "in .docsync/state.json yet\n"
            "  → pass --base main (or any revision) for this run"
            + ("" if is_git_repo(self.root) else ", or --base-dir <path> outside a git repo")
            + ",\n     or run `docsync snapshot` to record the current values as the baseline"
        )

    # -- the two derived views --------------------------------------------

    def audit(self) -> list[AuditFinding]:
        return audit(self.registry, self.facts_now())

    def plan(
        self, *, base: str = "", base_dir: str = "", allow_prose: bool = False
    ) -> ChangePlan:
        return build_plan(
            self.registry,
            self.facts_before(base=base, base_dir=base_dir),
            self.facts_now(),
            uploaded=self.state.uploaded(),
            allow_prose=allow_prose,
        )

    def snapshot(self) -> int:
        """Record *every* current value as the baseline. Free, offline.

        The blunt instrument, and correct only when you are asserting that the
        documents are already right — which is what ``docsync snapshot`` means.
        It is deliberately not what runs after an apply; see below.
        """
        table = self.facts_now()
        self.state.facts = table.as_snapshot()
        self.state.save()
        return len(self.state.facts)

    def advance_baseline(
        self, *, base: str = "", base_dir: str = "", allow_prose: bool = False
    ) -> list[str]:
        """Record only the facts that no document still needs changed.

        Using ``snapshot`` after an apply looks equivalent and quietly loses
        work. A run can legitimately end with facts outstanding — a prose
        change held back for a human, or the second changed fact in a document
        that takes two rounds — and recording *those* as synced tells the next
        run there is nothing to do. The document stays wrong and the tool stops
        mentioning it, which is the exact failure mode this build exists to
        prevent, arriving through the back door.

        So a fact's baseline only moves when every document carrying it is
        correct. Anything still outstanding keeps its old value and shows up
        again next time.
        """
        plan = self.plan(base=base, base_dir=base_dir, allow_prose=allow_prose)
        outstanding = {
            change.key
            for doc in plan.documents
            for change in (list(doc.to_send) + list(doc.unanchored))
        }
        table = self.facts_now()
        advanced: list[str] = []
        for change in plan.changes:
            if change.key in outstanding:
                continue
            value = table.values.get(change.key)
            if value is not None and value.ok and value.text is not None:
                self.state.facts[change.key] = value.text
                advanced.append(change.key)
        # A fact with no baseline at all is recorded as-is: it is new to the
        # registry, was never a change, and would otherwise stay unrecorded
        # for ever.
        for key, value in table.values.items():
            if key not in self.state.facts and value.ok and value.text is not None:
                self.state.facts[key] = value.text
        self.state.save()
        return advanced

    # -- the client --------------------------------------------------------

    def client(self, *, dry_run: bool = False, max_operations: int | None = None) -> SuperDocs:
        load_env(self.root / ".env", Path.cwd() / ".env")
        key = os.environ.get("SUPERDOCS_API_KEY", "")
        if dry_run and not key:
            # A dry run makes no call, so it must not demand a key. Being able
            # to cost a change without holding credentials is most of the point
            # of having a dry run at all.
            key = "sk_dry_run_placeholder"
        ledger = Ledger(
            limit=self.registry.budget if max_operations is None else max_operations,
            dry_run=dry_run,
        )
        return SuperDocs(
            key,
            base_url=os.environ.get("SUPERDOCS_BASE_URL", BASE_URL),
            ledger=ledger,
        )
