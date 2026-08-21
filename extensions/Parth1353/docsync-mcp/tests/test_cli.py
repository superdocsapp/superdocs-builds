"""The command line, driven as a subprocess.

Every test here runs with ``SUPERDOCS_API_KEY`` unset and
``SUPERDOCS_BASE_URL`` pointed at a closed port. Any command that quietly made
a network call would fail rather than pass slowly, which is the only way to
prove "free and offline" rather than assert it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import edit_file

DEAD = "http://127.0.0.1:1/v1"


def run(repo: Path, *args: str, key: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "SUPERDOCS_BASE_URL": DEAD}
    env.pop("SUPERDOCS_API_KEY", None)
    if key:
        env["SUPERDOCS_API_KEY"] = key
    return subprocess.run(
        [sys.executable, "-m", "docsync", *args, "--registry", str(repo)],
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
        cwd=str(repo),
    )


class TestFreeCommands:
    def test_facts(self, repo: Path):
        result = run(repo, "facts")
        assert result.returncode == 0
        assert "retry.max_attempts" in result.stdout
        assert "30 seconds" in result.stdout

    def test_facts_json(self, repo: Path):
        import json

        result = run(repo, "facts", "--json")
        data = json.loads(result.stdout)
        assert data["sla.uptime_target"] == "99.95%"
        assert isinstance(data["api.endpoints"], list)

    def test_facts_exits_nonzero_when_a_fact_cannot_be_read(self, repo: Path):
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = f()")
        result = run(repo, "facts")
        assert result.returncode == 1
        assert "unresolved" in result.stdout

    def test_audit_passes_on_the_example(self, repo: Path):
        result = run(repo, "audit")
        assert result.returncode == 0
        assert "anchored" in result.stdout
        assert "WEAK" in result.stdout  # the 1000 that is also the rate limit

    def test_audit_fails_when_a_covered_fact_cannot_be_read(self, repo: Path):
        edit_file(repo, "service.json", '"uptime_target": "99.95%"', '"uptime": "99.95%"')
        result = run(repo, "audit")
        assert result.returncode == 1
        assert "FAIL" in result.stdout

    def test_plan_without_a_baseline_says_what_to_do(self, repo: Path):
        result = run(repo, "plan")
        assert result.returncode == 1
        assert "no baseline" in result.stderr
        assert "--base" in result.stderr

    def test_snapshot_then_plan(self, repo: Path):
        assert run(repo, "snapshot").returncode == 0
        assert (repo / ".docsync" / "state.json").exists()

        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        result = run(repo, "plan")
        assert result.returncode == 0
        assert "Maximum retry attempts: 3  →  5" in result.stdout
        assert "2 billable operation(s)" in result.stdout
        # The restraint half of the claim.
        assert "KEEP  docs/sla-summary.md" in result.stdout
        # And the held-back prose change, named rather than dropped silently.
        assert "HELD BACK — Maximum retry attempts" in result.stdout

    def test_plan_against_a_git_revision(self, git_repo: Path):
        edit_file(git_repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        result = run(git_repo, "plan", "--base", "HEAD")
        assert result.returncode == 0
        assert "Maximum retry attempts: 3  →  5" in result.stdout

    def test_show_instruction(self, repo: Path):
        run(repo, "snapshot")
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        result = run(repo, "plan", "--show-instruction")
        assert 'Replace that one occurrence with "5"' in result.stdout
        assert "Do not reword anything else" in result.stdout


class TestDryRun:
    def test_costs_nothing_and_needs_no_key(self, repo: Path):
        run(repo, "snapshot")
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        result = run(repo, "apply", "--dry-run")
        assert result.returncode == 0
        assert "Nothing was sent and nothing was billed" in result.stdout
        assert "2 billable operation(s)" in result.stdout
        # Being able to cost a change without holding credentials is most of
        # the point of having a dry run.
        assert "SUPERDOCS_API_KEY" not in result.stderr

    def test_leaves_the_documents_alone(self, repo: Path):
        original = (repo / "docs/adr/0007-retry-policy.md").read_text()
        run(repo, "snapshot")
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        run(repo, "apply", "--dry-run")
        assert (repo / "docs/adr/0007-retry-policy.md").read_text() == original

    def test_a_blocked_plan_exits_two_before_anything_is_sent(self, repo: Path):
        run(repo, "snapshot")
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = f()")
        result = run(repo, "apply", "--dry-run", key="sk_not_used")
        assert result.returncode == 2
        assert "Refusing to send anything" in result.stdout

    def test_a_plan_over_budget_is_refused(self, repo: Path):
        run(repo, "snapshot")
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        result = run(repo, "apply", "--max-operations", "1", key="sk_not_used")
        assert result.returncode == 2
        assert "Refusing" in result.stdout

    def test_nothing_to_do_is_a_clean_exit(self, repo: Path):
        run(repo, "snapshot")
        result = run(repo, "apply", "--dry-run")
        assert result.returncode == 0
        assert "No tracked fact moved" in result.stdout


class TestErrors:
    def test_a_missing_registry_is_explained(self, tmp_path: Path):
        result = run(tmp_path, "facts")
        assert result.returncode == 1
        assert "no registry at" in result.stderr

    def test_approve_with_nothing_staged(self, repo: Path):
        result = run(repo, "approve")
        assert result.returncode == 1
        assert "nothing is staged" in result.stdout
