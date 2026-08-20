"""The registry file and the coverage declarations documents carry."""

from __future__ import annotations

from pathlib import Path

import pytest

from docsync.registry import Registry, RegistryError, coverage_of

GOOD = """
version: 1
facts:
  a.b:
    label: A thing
    from: src/x.py
    extract: python_constant:X
"""


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestLoading:
    def test_loads_the_example(self, repo: Path):
        registry = Registry.load(repo)
        assert registry.session_id == "docsync-example-provisioning"
        assert registry.budget == 20
        assert "retry.max_attempts" in registry.facts
        assert registry.facts["api.endpoints"].is_list
        assert not registry.facts["retry.max_attempts"].is_list

    def test_accepts_a_directory_or_the_file_itself(self, repo: Path):
        assert Registry.load(repo).root == Registry.load(repo / "docsync.yaml").root

    def test_missing_file_says_what_to_do(self, tmp_path: Path):
        with pytest.raises(RegistryError, match="no registry at"):
            Registry.load(tmp_path)

    def test_rejects_an_unknown_version(self, tmp_path: Path):
        write(tmp_path, "docsync.yaml", "version: 2\nfacts: {}\n")
        with pytest.raises(RegistryError, match="version 2"):
            Registry.load(tmp_path)

    def test_rejects_a_registry_with_no_facts(self, tmp_path: Path):
        write(tmp_path, "docsync.yaml", "version: 1\nfacts: {}\n")
        with pytest.raises(RegistryError, match="declares no facts"):
            Registry.load(tmp_path)

    def test_rejects_a_fact_with_no_source(self, tmp_path: Path):
        write(tmp_path, "docsync.yaml", "version: 1\nfacts:\n  a:\n    extract: regex:(x)\n")
        with pytest.raises(RegistryError, match="needs a `from:` path"):
            Registry.load(tmp_path)

    def test_rejects_a_format_without_the_placeholder(self, tmp_path: Path):
        # A format with no {value} produces identical text for every value,
        # which would make every comparison pass and every anchor wrong.
        write(
            tmp_path,
            "docsync.yaml",
            "version: 1\nfacts:\n  a:\n    from: x.py\n    extract: regex:(x)\n"
            '    format: "always the same"\n',
        )
        with pytest.raises(RegistryError, match=r"must contain \{value\}"):
            Registry.load(tmp_path)

    def test_rejects_a_source_path_that_escapes_the_root(self, tmp_path: Path):
        # A registry is a checked-in file whose contents this tool uploads to a
        # third-party API. `from: ../../../.ssh/id_rsa` in a pull request from a
        # stranger must fail rather than helpfully read the file.
        write(
            tmp_path,
            "docsync.yaml",
            "version: 1\nfacts:\n  a:\n    from: ../../../etc/passwd\n"
            "    extract: regex:(root)\n",
        )
        with pytest.raises(RegistryError, match="outside the registry root"):
            Registry.load(tmp_path)

    def test_resolve_refuses_to_leave_the_root(self, repo: Path):
        registry = Registry.load(repo)
        with pytest.raises(RegistryError, match="outside the registry root"):
            registry.resolve("../secrets.txt")

    def test_rejects_a_bad_budget(self, tmp_path: Path):
        write(
            tmp_path,
            "docsync.yaml",
            "version: 1\nbudget: -4\nfacts:\n  a:\n    from: x.py\n    extract: regex:(x)\n",
        )
        with pytest.raises(RegistryError, match="non-negative"):
            Registry.load(tmp_path)


class TestCoverage:
    def test_front_matter_declaration(self):
        covers, title = coverage_of(
            "---\ntitle: A doc\ndocsync:\n  covers:\n    - a.b\n    - c.d\n---\n\n# Heading\n"
        )
        assert covers == ["a.b", "c.d"]
        assert title == "A doc"

    def test_html_comment_declaration(self):
        covers, title = coverage_of("# Heading\n\n<!-- docsync:\ncovers: [a.b]\n-->\n")
        assert covers == ["a.b"]
        assert title == "Heading"

    def test_a_document_with_no_block_is_unmanaged(self):
        covers, title = coverage_of("# Just a document\n\nNothing to declare.\n")
        assert covers is None
        assert title == "Just a document"

    def test_front_matter_without_a_docsync_block_is_unmanaged(self):
        covers, _ = coverage_of("---\ntitle: X\n---\n\nbody\n")
        assert covers is None

    def test_a_single_string_is_accepted_as_a_list(self):
        covers, _ = coverage_of("---\ndocsync:\n  covers: a.b\n---\n")
        assert covers == ["a.b"]

    def test_duplicates_are_collapsed(self):
        covers, _ = coverage_of("---\ndocsync:\n  covers: [a.b, a.b]\n---\n")
        assert covers == ["a.b"]

    def test_a_block_with_no_covers_is_loud(self):
        # Being quiet here would mean "I wrote a declaration and the tool
        # ignored it", which is the failure worth shouting about.
        with pytest.raises(RegistryError, match="no `covers` list"):
            coverage_of("---\ndocsync:\n  notes: hello\n---\n")

    def test_malformed_yaml_in_front_matter_is_loud(self):
        with pytest.raises(RegistryError, match="not valid YAML"):
            coverage_of("---\ndocsync:\n  covers: [a, b\n---\n")


class TestDocuments:
    def test_finds_only_managed_documents(self, repo: Path):
        registry = Registry.load(repo)
        paths = [doc.path for doc in registry.documents()]
        assert paths == [
            "docs/adr/0007-retry-policy.md",
            "docs/runbook-circuit-activation.md",
            "docs/sla-summary.md",
            "docs/spec-provisioning-api.md",
        ]
        assert "docs/contributing.md" not in paths

    def test_a_typo_in_a_coverage_list_is_an_error(self, repo: Path):
        # Left as a skip, a mistyped key would quietly exclude the document
        # from every future change — the exact failure this tool prevents.
        path = repo / "docs/sla-summary.md"
        path.write_text(
            path.read_text().replace("sla.uptime_target", "sla.uptme_target"), encoding="utf-8"
        )
        with pytest.raises(RegistryError, match="unknown fact"):
            Registry.load(repo).documents()

    def test_documents_carrying_computes_the_impact_set(self, repo: Path):
        registry = Registry.load(repo)
        carrying = [d.path for d in registry.documents_carrying("sla.p1_response_minutes")]
        assert carrying == ["docs/runbook-circuit-activation.md", "docs/sla-summary.md"]

    def test_uncovered_facts_are_reported(self, repo: Path):
        registry = Registry.load(repo)
        assert registry.uncovered_facts() == []

        path = repo / "docs/spec-provisioning-api.md"
        path.write_text(
            path.read_text().replace("    - api.default_bandwidth_mbps\n", ""), encoding="utf-8"
        )
        assert Registry.load(repo).uncovered_facts() == ["api.default_bandwidth_mbps"]

    def test_titles_fall_back_to_the_first_heading(self, tmp_path: Path):
        write(tmp_path, "docsync.yaml", GOOD)
        write(tmp_path, "docs/x.md", "---\ndocsync:\n  covers: [a.b]\n---\n\n# The Title\n")
        docs = Registry.load(tmp_path).documents()
        assert docs[0].title == "The Title"
