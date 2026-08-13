import json
import os
from dataclasses import dataclass


@dataclass
class RunPlan:
    """What a single invocation of the pipeline should do.

    - ``changed_sources``: sources whose bytes differ from the last completed run
    - ``sections_to_draft``: sections that still need drafting (resume runs exclude
      sections already completed by an interrupted run)
    - ``resume_session_id``: when not None, continue the interrupted run's SuperDocs
      session instead of bootstrapping a new one
    """

    changed_sources: set[str]
    sections_to_draft: list[tuple[str, str, list[str]]]
    resume_session_id: str | None = None
    is_resume: bool = False

    @property
    def is_noop(self) -> bool:
        """Nothing to do: no sources changed and no run to resume."""
        return not self.changed_sources and self.resume_session_id is None


class Manifest:
    def __init__(self, filepath: str):
        with open(filepath, "r") as f:
            self.data = json.load(f)

    @property
    def sections(self) -> dict:
        return self.data.get("sections", {})

    def get_all_sources(self) -> set[str]:
        sources: set[str] = set()
        for data in self.sections.values():
            for source in data.get("sources", []):
                sources.add(source)
        return sources

    def get_all_section_ids(self) -> list[str]:
        return list(self.sections.keys())

    def get_affected_sections(self, changed_sources: set[str]) -> list[tuple[str, str, list[str]]]:
        affected = []
        for section, data in self.sections.items():
            section_sources = data.get("sources", [])
            if any(src in changed_sources for src in section_sources):
                affected.append((section, data["title"], section_sources))
        return affected


def detect_changed_sources(
    sources: set[str],
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
) -> set[str]:
    changed = set()
    for source in sources:
        if new_hashes.get(source) != old_hashes.get(source):
            changed.add(source)
    return changed


def select_upload_target(final_path: str, shell_path: str) -> str:
    if os.path.exists(final_path):
        return final_path
    return shell_path


def plan_run(
    manifest: "Manifest",
    old_state: dict,
    new_hashes: dict,
    sources: set[str],
) -> RunPlan:
    """Decide what this invocation should do before touching the API.

    Pure function so the resume/early-exit logic is testable offline:
    - no sources changed and nothing interrupted -> noop
    - interrupted run whose source bytes are unchanged -> resume the same session,
      skip sections already completed
    - otherwise -> fresh incremental run
    """
    old_hashes = old_state.get("hashes", {})
    changed_sources = detect_changed_sources(sources, old_hashes, new_hashes)
    affected = manifest.get_affected_sections(changed_sources)

    in_progress = old_state.get("in_progress")
    if in_progress and in_progress.get("source_hashes") == dict(new_hashes):
        completed = set(in_progress.get("completed_sections", []))
        remaining = [s for s in affected if s[0] not in completed]
        return RunPlan(
            changed_sources=changed_sources,
            sections_to_draft=remaining,
            resume_session_id=old_state.get("session_id"),
            is_resume=True,
        )

    if not changed_sources:
        return RunPlan(changed_sources=set(), sections_to_draft=[])

    return RunPlan(changed_sources=changed_sources, sections_to_draft=affected)


def apply_budget(
    plan: RunPlan,
    manifest: "Manifest",
    old_state: dict,
    max_sections: int | None,
) -> tuple[RunPlan, bool]:
    """Truncate the draft list to ``max_sections`` (None = unlimited).

    Returns ``(plan, partial_run)``. ``partial_run`` is True when sections that
    still need drafting were left out of this run — either by the budget or by
    nothing at all — which means the run must NOT mark its sources complete, so
    a later full run resumes where this one stopped.
    """
    if max_sections is not None:
        plan.sections_to_draft = plan.sections_to_draft[:max_sections]

    affected_ids = {s[0] for s in manifest.get_affected_sections(plan.changed_sources)}
    completed_ids = set((old_state.get("in_progress") or {}).get("completed_sections", []))
    drafted_ids = {s[0] for s in plan.sections_to_draft}
    partial_run = bool(affected_ids - completed_ids - drafted_ids)
    return plan, partial_run
