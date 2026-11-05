import json
import os
import tempfile
import unittest

from manifest import (
    Manifest,
    apply_budget,
    detect_changed_sources,
    plan_run,
    select_upload_target,
)

MANIFEST_SECTIONS = {
    "sections": {
        "2.5.1": {
            "title": "Clinical Pharmacology",
            "sources": ["module5/study_report_1.txt"],
        },
        "2.5.2": {
            "title": "Clinical Efficacy",
            "sources": ["module5/study_report_2.txt"],
        },
        "2.5.3": {
            "title": "Clinical Safety",
            "sources": ["module5/study_report_2.txt"],
        },
    }
}

ALL_SOURCES = {"module5/study_report_1.txt", "module5/study_report_2.txt"}
H1 = {"module5/study_report_1.txt": "aaa"}
H2 = {"module5/study_report_2.txt": "bbb"}
H_BOTH = {**H1, **H2}


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.manifest_path = os.path.join(self.tempdir, "manifest.json")
        with open(self.manifest_path, "w") as f:
            json.dump(MANIFEST_SECTIONS, f)
        self.manifest = Manifest(self.manifest_path)

    def test_get_all_sources(self):
        self.assertEqual(
            self.manifest.get_all_sources(),
            {"module5/study_report_1.txt", "module5/study_report_2.txt"},
        )

    def test_get_affected_sections_for_one_source(self):
        affected = self.manifest.get_affected_sections({"module5/study_report_2.txt"})
        section_ids = [section for section, _, _ in affected]
        self.assertEqual(section_ids, ["2.5.2", "2.5.3"])

    def test_detect_changed_sources_on_first_run(self):
        changed = detect_changed_sources(
            {"module5/study_report_1.txt"},
            old_hashes={},
            new_hashes={"module5/study_report_1.txt": "abc"},
        )
        self.assertEqual(changed, {"module5/study_report_1.txt"})

    def test_detect_changed_sources_when_unchanged(self):
        changed = detect_changed_sources(
            {"module5/study_report_1.txt"},
            old_hashes={"module5/study_report_1.txt": "abc"},
            new_hashes={"module5/study_report_1.txt": "abc"},
        )
        self.assertEqual(changed, set())

    def test_select_upload_target_prefers_final_export(self):
        final_path = os.path.join(self.tempdir, "final.docx")
        shell_path = os.path.join(self.tempdir, "shell.docx")
        with open(final_path, "w") as f:
            f.write("final")
        with open(shell_path, "w") as f:
            f.write("shell")
        self.assertEqual(select_upload_target(final_path, shell_path), final_path)

    def test_select_upload_target_falls_back_to_shell(self):
        shell_path = os.path.join(self.tempdir, "shell.docx")
        with open(shell_path, "w") as f:
            f.write("shell")
        self.assertEqual(
            select_upload_target(os.path.join(self.tempdir, "missing.docx"), shell_path),
            shell_path,
        )


class TestRunPlan(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.manifest_path = os.path.join(self.tempdir, "manifest.json")
        with open(self.manifest_path, "w") as f:
            json.dump(MANIFEST_SECTIONS, f)
        self.manifest = Manifest(self.manifest_path)

    def _state(self, **overrides) -> dict:
        state = {"session_id": None, "hashes": {}, "in_progress": None}
        state.update(overrides)
        return state

    def test_first_run_plans_all_sections(self):
        plan = plan_run(self.manifest, {}, H_BOTH, ALL_SOURCES)

        self.assertFalse(plan.is_noop)
        self.assertFalse(plan.is_resume)
        self.assertEqual(plan.changed_sources, ALL_SOURCES)
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.1", "2.5.2", "2.5.3"])

    def test_no_changes_is_noop(self):
        state = self._state(hashes=H_BOTH)
        plan = plan_run(self.manifest, state, H_BOTH, ALL_SOURCES)

        self.assertTrue(plan.is_noop)
        self.assertEqual(plan.sections_to_draft, [])

    def test_only_dependent_sections_change(self):
        state = self._state(hashes=H_BOTH)
        plan = plan_run(self.manifest, state, {**H1, "module5/study_report_2.txt": "zzz"}, ALL_SOURCES)

        self.assertEqual(plan.changed_sources, {"module5/study_report_2.txt"})
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.2", "2.5.3"])

    def test_interrupted_run_resumes_and_skips_completed(self):
        state = self._state(
            session_id="sess_abc",
            in_progress={
                "source_hashes": H_BOTH,
                "completed_sections": ["2.5.1", "2.5.2"],
            },
        )
        plan = plan_run(self.manifest, state, H_BOTH, ALL_SOURCES)

        self.assertTrue(plan.is_resume)
        self.assertEqual(plan.resume_session_id, "sess_abc")
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.3"])

    def test_interrupted_run_with_all_sections_done_still_resumes(self):
        state = self._state(
            session_id="sess_abc",
            in_progress={"source_hashes": H_BOTH, "completed_sections": ["2.5.1", "2.5.2", "2.5.3"]},
        )
        plan = plan_run(self.manifest, state, H_BOTH, ALL_SOURCES)

        self.assertTrue(plan.is_resume)
        self.assertEqual(plan.sections_to_draft, [])

    def test_sources_changed_again_after_crash_falls_back_to_fresh_run(self):
        state = self._state(
            session_id="sess_abc",
            hashes=H_BOTH,
            in_progress={"source_hashes": H_BOTH, "completed_sections": ["2.5.1"]},
        )
        new_hashes = {"module5/study_report_1.txt": "aaa", "module5/study_report_2.txt": "zzz"}
        plan = plan_run(self.manifest, state, new_hashes, ALL_SOURCES)

        self.assertFalse(plan.is_resume)
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.2", "2.5.3"])


class TestApplyBudget(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.manifest_path = os.path.join(self.tempdir, "manifest.json")
        with open(self.manifest_path, "w") as f:
            json.dump(MANIFEST_SECTIONS, f)
        self.manifest = Manifest(self.manifest_path)

    def test_truncated_run_is_partial(self):
        plan = plan_run(self.manifest, {}, H_BOTH, ALL_SOURCES)
        plan, partial = apply_budget(plan, self.manifest, {}, max_sections=1)

        self.assertTrue(partial)
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.1"])

    def test_unlimited_run_is_not_partial(self):
        plan = plan_run(self.manifest, {}, H_BOTH, ALL_SOURCES)
        plan, partial = apply_budget(plan, self.manifest, {}, max_sections=None)

        self.assertFalse(partial)
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.1", "2.5.2", "2.5.3"])

    def test_resume_with_completed_sections_is_not_partial(self):
        state = {
            "session_id": "sess_abc",
            "in_progress": {"source_hashes": H_BOTH, "completed_sections": ["2.5.1", "2.5.2"]},
        }
        plan = plan_run(self.manifest, state, H_BOTH, ALL_SOURCES)
        plan, partial = apply_budget(plan, self.manifest, state, max_sections=None)

        self.assertFalse(partial)
        self.assertEqual([s[0] for s in plan.sections_to_draft], ["2.5.3"])

    def test_resume_truncated_to_zero_is_partial(self):
        state = {
            "session_id": "sess_abc",
            "in_progress": {"source_hashes": H_BOTH, "completed_sections": ["2.5.1"]},
        }
        plan = plan_run(self.manifest, state, H_BOTH, ALL_SOURCES)
        plan, partial = apply_budget(plan, self.manifest, state, max_sections=0)

        self.assertTrue(partial)
        self.assertEqual(plan.sections_to_draft, [])


if __name__ == "__main__":
    unittest.main()
