import json
import os
import tempfile
import unittest

from manifest import Manifest, detect_changed_sources, select_upload_target


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.manifest_path = os.path.join(self.tempdir, "manifest.json")
        with open(self.manifest_path, "w") as f:
            json.dump(
                {
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
                },
                f,
            )
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


if __name__ == "__main__":
    unittest.main()
