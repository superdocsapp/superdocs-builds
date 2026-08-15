"""The readers, against the corpus.

Two things are being tested here and they are not the same thing. Most of it is
"does this reader find what is in the file". The more valuable half is the
boundary tests: does the reader *decline* to answer when the file does not
settle the question. `parse_threshold` returning None for `absent(up)` is a
feature; a reader that invents a number there is how a checker ends up
confidently wrong.

Every test names a real file in `fixtures/`, so a fixture that changes shape
breaks the reader test rather than silently changing what the checker measures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.config import Config, Mappings
from reconciler.estate import Estate
from reconciler.readers import alerts, catalog, ci, dashboards, escalation, kubernetes, terraform


@pytest.fixture(scope="session")
def paths(infra_dir: Path) -> tuple[Path, ...]:
    return (infra_dir,)


@pytest.fixture(scope="session")
def estate(infra_dir: Path) -> Estate:
    return Estate(
        alerts=alerts.read_rules((infra_dir,)),
        workloads=kubernetes.read_workloads((infra_dir,)),
        workflows=ci.read_workflows((infra_dir,)),
        terraform=terraform.read_terraform((infra_dir,)),
        components=catalog.read_catalog((infra_dir,)),
        policies=escalation.read_policies((infra_dir,)),
        dashboards=dashboards.read_dashboards((infra_dir,)),
        mappings=Mappings.load(),
    )


# ----------------------------------------------------------------- alerts ---


def test_every_alert_in_the_corpus_is_found(paths: tuple[Path, ...]) -> None:
    rules = alerts.read_rules(paths)
    assert {r.name for r in rules} == {
        "PaymentsApiHighLatency",
        "PaymentsApiErrorBudgetBurn",
        "PaymentsDeadLetterQueueGrowing",
        "TrackingIngestPodRestarts",
        "TrackingIngestLag",
        "LabelPrinterQueueDepth",
        "ManifestWorkerStalled",
    }


def test_the_threshold_comes_from_the_end_of_the_expression(paths: tuple[Path, ...]) -> None:
    """The quantile's 0.99 and the rate's 5m are not thresholds."""
    latency = next(r for r in alerts.read_rules(paths) if r.name == "PaymentsApiHighLatency")
    assert latency.operator == ">"
    assert latency.threshold == 1.2
    assert latency.duration_seconds == 600


def test_an_expression_with_no_trailing_comparison_yields_no_threshold() -> None:
    """The honest None. A claim about this alert can only be unverifiable."""
    assert alerts.parse_threshold("absent(up{job='payments'})") is None
    assert alerts.parse_threshold("changes(process_start_time_seconds[1h]) > 3") == (">", 3.0)


def test_the_runbook_url_resolves_to_a_page_id(paths: tuple[Path, ...]) -> None:
    rules = {r.name: r for r in alerts.read_rules(paths)}
    assert rules["PaymentsApiHighLatency"].runbook_page_id == "1001"
    assert rules["TrackingIngestLag"].runbook_page_id == "1099"
    assert rules["ManifestWorkerStalled"].runbook_page_id is None


def test_every_alert_carries_evidence_that_resolves(paths: tuple[Path, ...]) -> None:
    """Rule 8 at the reader, before any finding is built on top of it."""
    from reconciler.config import PROJECT_ROOT

    for rule in alerts.read_rules(paths):
        path = PROJECT_ROOT / rule.source.file
        assert path.is_file(), f"{rule.name} cites {rule.source}"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert 1 <= rule.source.line <= len(lines)
        window = "\n".join(lines[max(0, rule.source.line - 3) : rule.source.line + 2])
        assert rule.name in window, f"{rule.name} is not near {rule.source}"


# ------------------------------------------------------------- kubernetes ---


def test_workloads_are_read_with_namespace_and_replicas(paths: tuple[Path, ...]) -> None:
    workloads = {w.name: w for w in kubernetes.read_workloads(paths)}
    assert set(workloads) == {
        "payments-api",
        "tracking-ingest",
        "label-printer",
        "manifest-worker",
    }
    assert workloads["payments-api"].namespace == "payments"
    assert workloads["payments-api"].replicas == 6
    assert workloads["payments-api"].ref == "deployment/payments-api@payments"


def test_container_limits_and_probes_are_read(paths: tuple[Path, ...]) -> None:
    payments = next(w for w in kubernetes.read_workloads(paths) if w.name == "payments-api")
    container = payments.containers[0]
    assert container.memory_limit == "2Gi"
    assert container.readiness_path == "/healthz"
    assert container.image_tag == "2.14.0"


def test_a_multi_document_manifest_yields_every_resource(tmp_path: Path) -> None:
    """Reading only the first document silently loses most of a cluster."""
    manifest = tmp_path / "many.yaml"
    manifest.write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: a\n  namespace: n\n"
        "---\n"
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: svc\n"
        "---\n"
        "apiVersion: apps/v1\nkind: StatefulSet\nmetadata:\n  name: b\n  namespace: n\n",
        encoding="utf-8",
    )
    found = kubernetes.read_workloads_file(manifest)
    assert [w.name for w in found] == ["a", "b"]  # the Service is not a workload


def test_an_unparseable_yaml_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    """A Helm template in the tree must not fail the whole sweep."""
    template = tmp_path / "deployment.yaml"
    template.write_text("kind: Deployment\nmetadata:\n  name: {{ .Values.name }}\n  : :\n")
    assert kubernetes.read_workloads_file(template) == []


# --------------------------------------------------------------------- ci ---


def test_github_workflow_jobs_and_environments(paths: tuple[Path, ...]) -> None:
    workflows = {w.repo: w for w in ci.read_workflows(paths)}
    payments = workflows["payments-api"]
    assert {j.name for j in payments.jobs} == {
        "build",
        "test",
        "deploy-staging",
        "deploy-production",
        "manual-rollback",
    }
    assert payments.job("deploy-production").environment == "production"
    assert payments.job("deploy-production").gated
    assert not payments.job("build").gated


def test_the_renamed_job_is_absent_under_its_old_name(paths: tuple[Path, ...]) -> None:
    """The planted drift, seen from the ground-truth side."""
    payments = next(w for w in ci.read_workflows(paths) if w.repo == "payments-api")
    assert payments.job("rollback-production") is None
    assert payments.job("manual-rollback") is not None


def test_gitlab_jobs_are_the_keys_that_are_not_reserved_words(tmp_path: Path) -> None:
    path = tmp_path / ".gitlab-ci.yml"
    path.write_text(
        "stages: [build, deploy]\n"
        "variables:\n  FOO: bar\n"
        ".template:\n  script: echo\n"
        "build-app:\n  stage: build\n  script: make\n"
        "deploy-prod:\n  stage: deploy\n  environment:\n    name: production\n",
        encoding="utf-8",
    )
    workflow = ci.read_gitlab_workflow(path)
    assert {j.name for j in workflow.jobs} == {"build-app", "deploy-prod"}
    assert workflow.job("deploy-prod").environment == "production"


# -------------------------------------------------------------- terraform ---


def test_terraform_literals_are_read(paths: tuple[Path, ...]) -> None:
    blocks = terraform.read_terraform(paths)
    db = terraform.find_resource(blocks, "aws_db_instance", "payments")
    assert db is not None
    assert db.get("identifier") == "meridian-payments-prod"
    assert db.get("backup_retention_period") == "14"
    assert db.get("multi_az") == "true"
    assert db.address == "aws_db_instance.payments"


def test_a_provider_block_gives_the_region(paths: tuple[Path, ...]) -> None:
    blocks = terraform.read_terraform(paths)
    provider = next(b for b in blocks if b.type == "provider")
    assert provider.get("region") == "eu-west-1"


def test_nested_blocks_are_reachable(paths: tuple[Path, ...]) -> None:
    blocks = terraform.read_terraform(paths)
    plan = terraform.find_resource(blocks, "aws_backup_plan", "payments")
    rule = plan.nested("rule")[0]
    assert rule.get("schedule") == "cron(0 3 * * ? *)"
    assert plan.find_attribute("delete_after") == ("35", rule.nested("lifecycle")[0])


def test_a_reference_is_recorded_as_unresolved_not_guessed(paths: tuple[Path, ...]) -> None:
    """`replicate_source_db = aws_db_instance.payments.identifier` is not a value.

    The whole scanner rests on this boundary: literals are ground truth,
    everything else is something we do not know and say we do not know.
    """
    blocks = terraform.read_terraform(paths)
    replica = terraform.find_resource(blocks, "aws_db_instance", "payments_replica")
    assert "replicate_source_db" in replica.unresolved
    assert "identifier" not in replica.unresolved


def test_braces_and_hashes_inside_strings_do_not_break_the_scanner(tmp_path: Path) -> None:
    path = tmp_path / "tricky.tf"
    path.write_text(
        'resource "aws_s3_bucket" "b" {\n'
        '  bucket = "not-a-comment#and-not-a-{brace}"\n'
        "  # a real comment with a } in it\n"
        '  tags = { Name = "x" }\n'
        "}\n"
        'resource "aws_s3_bucket" "c" {\n  bucket = "second"\n}\n',
        encoding="utf-8",
    )
    blocks = terraform.read_terraform_file(path)
    assert [b.labels[1] for b in blocks] == ["b", "c"]
    assert blocks[0].get("bucket") == "not-a-comment#and-not-a-{brace}"


def test_an_interpolated_string_is_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "interp.tf"
    path.write_text('resource "aws_db_instance" "x" {\n  identifier = "${var.env}-payments"\n}\n')
    block = terraform.read_terraform_file(path)[0]
    assert "identifier" in block.unresolved


# ---------------------------------------------------------------- catalog ---


def test_catalog_components_and_annotations(paths: tuple[Path, ...]) -> None:
    components = {c.name: c for c in catalog.read_catalog(paths)}
    payments = components["payments-api"]
    assert payments.owner == "team-payments"
    assert payments.tier == "1"
    assert payments.workload_ref == "deployment/payments-api@payments"
    assert payments.escalation_policy == "payments-core-oncall"
    assert payments.dashboard_uid == "abc123"


def test_former_names_are_read(paths: tuple[Path, ...]) -> None:
    tracking = next(c for c in catalog.read_catalog(paths) if c.name == "tracking-ingest")
    assert tracking.former_names == ("tracking-api",)
    assert tracking.names == ("tracking-ingest", "tracking-api")


# ------------------------------------------------------------- escalation ---


def test_policies_are_read_with_their_spellings(paths: tuple[Path, ...]) -> None:
    policies = {p.name: p for p in escalation.read_policies(paths)}
    core = policies["payments-core-oncall"]
    assert core.display_name == "Payments Core"
    assert "Payments Core rota" in core.spellings
    assert core.services == ("payments-api",)
    assert core.level_after(15).target == "payments-core-secondary"


# ------------------------------------------------------------- dashboards ---


def test_dashboards_are_read_by_uid(paths: tuple[Path, ...]) -> None:
    found = {d.uid: d for d in dashboards.read_dashboards(paths)}
    assert found["abc123"].title == "Payments overview"
    assert "zzz999" not in found


def test_a_uid_is_pulled_out_of_a_grafana_url() -> None:
    assert dashboards.uid_in("https://grafana.example/d/abc123/payments-overview") == "abc123"
    assert dashboards.uid_in("https://example.com/nothing") is None


# ----------------------------------------------------------- the estate ----


def test_a_current_name_resolves_directly(estate: Estate) -> None:
    resolution = estate.resolve("payments-api")
    assert resolution.via == "workload"
    assert resolution.workload.namespace == "payments"
    assert not resolution.renamed


def test_a_former_name_resolves_and_is_reported_as_renamed(estate: Estate) -> None:
    """The finding that would otherwise have to be `unverifiable`."""
    resolution = estate.resolve("tracking-api")
    assert resolution.via == "former-name"
    assert resolution.renamed
    assert resolution.current_name == "tracking-ingest"


def test_a_declared_mapping_resolves_a_prose_phrase(estate: Estate) -> None:
    resolution = estate.resolve("the payments service")
    assert resolution.via == "declared-mapping"
    assert resolution.current_name == "payments-api"


def test_a_decommissioned_service_resolves_to_nothing(estate: Estate) -> None:
    resolution = estate.resolve("notify-gateway")
    assert not resolution.resolved
    assert resolution.via == "none"


def test_there_is_no_fuzzy_fallback(estate: Estate) -> None:
    """A near-miss must not resolve.

    `payment-api` is one character from a real service. Matching it would
    produce a confident finding about the wrong thing, which is a worse outcome
    than one unverifiable line in a report.
    """
    assert not estate.resolve("payment-api").resolved
    assert not estate.resolve("payments").resolved


def test_the_estate_loads_from_config_defaults() -> None:
    """A stranger's first run has somewhere to point: the corpus."""
    estate = Estate.load(Config.load())
    assert estate.summary()["alerts"] == 7
    assert estate.summary()["workloads"] == 4
