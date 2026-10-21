from dataclasses import replace
from itertools import combinations

from job_architecture.architecture import build_architecture
from job_architecture.cluster import (
    build_vectors,
    cluster_corpus,
    evidence_signature,
    nearest_neighbors,
    occupationally_compatible,
    similarity_text,
)
from job_architecture.evidence import extract_role_evidence
from job_architecture.fixtures import load_corpus
from job_architecture.models import FitStatus, RoleAssessment, RoleEvidence, SourceReference


def test_title_is_not_in_similarity_input() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-swe-ii-payments")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    blob = similarity_text(evidence).lower()
    assert evidence.title.lower() not in blob
    mutated = replace(evidence, title="Vice President of Engineering")
    assert evidence_signature(mutated) == evidence_signature(evidence)


def test_title_swap_preserves_neighbors_and_cluster() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    evidences = [
        extract_role_evidence(parsed, corpus.manifest.organization)
        for parsed in corpus.job_descriptions
    ]
    target_id = "ns-swe-ii-payments"
    index = next(i for i, item in enumerate(evidences) if item.role_id == target_id)
    original = evidences[index]
    mutated = replace(original, title="Distinguished Fellow, Payments")
    swapped = list(evidences)
    swapped[index] = mutated

    vectors_original = build_vectors(evidences)
    vectors_swapped = build_vectors(swapped)
    assert nearest_neighbors(vectors_original, target_id, k=4) == nearest_neighbors(
        vectors_swapped, target_id, k=4
    )

    clustering_original = result.clustering
    clustering_swapped = cluster_corpus(swapped, result.assessments)
    original_members = set(clustering_original.cluster_for_role(target_id).member_role_ids)
    swapped_members = set(clustering_swapped.cluster_for_role(target_id).member_role_ids)
    assert original_members == swapped_members


def test_solutions_architect_is_bridge_not_core() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    assert "ns-solutions-architect" in result.unclustered_role_ids
    assert "ns-solutions-architect" not in {
        role_id for cluster in result.clusters for role_id in cluster.member_role_ids
    }
    bridge = next(item for item in result.clustering.bridges if item.role_id == "ns-solutions-architect")
    assert bridge.nearest_cluster_id is not None
    assert bridge.alternative_cluster_id is not None
    assert bridge.is_bridge


def test_developer_advocate_stays_outside_standard_clusters() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    assert "ns-developer-advocate" in result.unclustered_role_ids
    assert result.assessment_for("ns-developer-advocate").fit_status is FitStatus.MISFIT
    for cluster in result.clusters:
        assert "ns-developer-advocate" not in cluster.member_role_ids


def test_medical_science_liaison_unclustered() -> None:
    corpus = load_corpus("corpus-b")
    result = build_architecture(corpus)
    assert "mh-medical-science-liaison" in result.unclustered_role_ids
    for cluster in result.clusters:
        assert "mh-medical-science-liaison" not in cluster.member_role_ids


def test_sparse_roles_are_not_forced_into_clusters() -> None:
    for corpus_id, role_id in (
        ("corpus-a", "ns-program-coordinator"),
        ("corpus-b", "mh-associate-special-programs"),
    ):
        result = build_architecture(load_corpus(corpus_id))
        assert role_id in result.unclustered_role_ids
        for cluster in result.clusters:
            assert role_id not in cluster.member_role_ids


def test_clusters_are_labeled_after_grouping() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    assert result.clusters
    labeled = [cluster for cluster in result.clusters if cluster.proposed_family]
    assert labeled
    engineering = [cluster for cluster in labeled if cluster.proposed_family == "engineering"]
    assert engineering
    assert len(engineering[0].member_role_ids) >= 2
    for cluster in result.clusters:
        assert cluster.cohesion >= 0
        assert cluster.notes
        if cluster.proposed_family:
            assert cluster.label_confidence is not None
            assert 0 <= cluster.label_confidence <= 1


def test_clustering_uses_corpus_neighbors_not_family_shortcut() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    evidences = [
        extract_role_evidence(parsed, corpus.manifest.organization)
        for parsed in corpus.job_descriptions
    ]
    vectors = build_vectors(evidences)
    neighbors = nearest_neighbors(vectors, "ns-swe-backend", k=3)
    assert neighbors
    assert neighbors[0][1] > 0
    corpus_ids = {item.role_id for item in evidences}
    assert {role_id for role_id, _score in neighbors} <= corpus_ids
    assert result.clustering.vectors


def _synthetic_evidence(role_id: str, *, title: str, organization: str, kind: str) -> RoleEvidence:
    if kind == "engineering":
        body = dict(
            responsibilities=[
                "Implement and operate backend APIs for production HTTP services.",
                "Own on-call, pull requests, observability, and Kubernetes runbooks.",
            ],
            scope="Two to three backend services on the platform.",
            autonomy="Local technical choices within published platform standards.",
            complexity="Multi-tenant API contracts and production debugging.",
            impact="Downstream product teams depend on these APIs.",
            leadership="Mentorship through review; no direct reports.",
            people_management="This is not a people-management role. You do not hire.",
            stakeholder_breadth="- Product engineers\n- SRE\n- Security",
            domain_depth="Backend APIs, service mesh, CI/CD, production HTTP services.",
            decision_making_authority="Service-local decisions; interfaces need review.",
        )
    elif kind == "engineering_variant":
        body = dict(
            responsibilities=[
                "Operate backend APIs and production HTTP services with on-call ownership.",
                "Review pull requests and keep Kubernetes observability runbooks current.",
            ],
            scope="Named backend services shared by product squads.",
            autonomy="Chooses implementation details inside existing platform standards.",
            complexity="Multi-tenant API and failover work.",
            impact="Product teams consume these backend APIs.",
            leadership="Pairs on pull requests; does not manage people.",
            people_management="Not a people-management role. You do not write reviews.",
            stakeholder_breadth="- Backend peers\n- SRE\n- Product",
            domain_depth="Kubernetes, backend APIs, CI/CD, production debugging.",
            decision_making_authority="Service-local sequencing.",
        )
    elif kind == "finance":
        body = dict(
            responsibilities=[
                "Build the company forecast and explain monthly variance to the operating budget.",
                "Own financial planning, the headcount model, and quarterly close commentary.",
            ],
            scope="Company plan and variance analysis.",
            autonomy="Independent within published finance standards.",
            complexity="Forecasting and variance across several product lines.",
            impact="Company-wide planning accuracy.",
            leadership="May answer a colleague; no reports.",
            people_management="This is not a people-management role. You do not hire.",
            stakeholder_breadth="- Finance leadership\n- Department heads",
            domain_depth="FP&A, forecasting, variance analysis, financial planning.",
            decision_making_authority="Forecast commentary; budget changes need review.",
        )
    else:
        body = dict(
            responsibilities=[
                "Maintain the quarterly forecast pack and variance notes for the operating budget.",
                "Refresh financial planning models used in the company plan.",
            ],
            scope="Named financial planning workstream.",
            autonomy="Follows existing finance checklist.",
            complexity="Variance analysis and headcount commentary.",
            impact="Planning cycle for the company plan.",
            leadership="No mentorship expectation.",
            people_management="Not a people-management role.",
            stakeholder_breadth="- FP&A peers\n- Controllership",
            domain_depth="Financial planning, forecasting, variance, operating budget.",
            decision_making_authority="Drafts forecast; does not sign the plan.",
        )
    return RoleEvidence(
        role_id=role_id,
        title=title,
        organization=organization,
        team="Example",
        source_references=[SourceReference(document_id=role_id, locator="responsibilities")],
        **body,
    )


def _core_assessment(role_id: str) -> RoleAssessment:
    # Independent family labels are identical on purpose. Clustering must
    # still partition by evidence similarity, not by those labels.
    return RoleAssessment(
        role_id=role_id,
        fit_status=FitStatus.STRONG_FIT,
        confidence=0.9,
        proposed_family="engineering",
        proposed_track="individual_contributor",
        proposed_level="IC3",
    )


def test_clustering_is_corpus_level_not_hardcoded_ids() -> None:
    left_eng = _synthetic_evidence("alpha", title="Role A", organization="Org One", kind="engineering")
    right_eng = _synthetic_evidence("beta", title="Role B", organization="Org One", kind="engineering_variant")
    finance = _synthetic_evidence("gamma", title="Role C", organization="Org One", kind="finance")
    evidences = [left_eng, right_eng, finance]
    assessments = [_core_assessment(item.role_id) for item in evidences]
    clustering = cluster_corpus(evidences, assessments)

    eng_cluster = clustering.cluster_for_role("alpha")
    assert eng_cluster is not None
    assert set(eng_cluster.member_role_ids) >= {"alpha", "beta"}
    assert "gamma" not in eng_cluster.member_role_ids

    finance_cluster = clustering.cluster_for_role("gamma")
    assert finance_cluster is not None
    assert "alpha" not in finance_cluster.member_role_ids

    # Renaming ids, titles, and the employer must not change the partition.
    renamed = [
        replace(left_eng, role_id="x1", title="Chief Wizard", organization="Other Co"),
        replace(right_eng, role_id="x2", title="Intern", organization="Other Co"),
        replace(finance, role_id="x3", title="CFO", organization="Other Co"),
    ]
    renamed_assessments = [
        replace(assessments[0], role_id="x1"),
        replace(assessments[1], role_id="x2"),
        replace(assessments[2], role_id="x3"),
    ]
    renamed_clustering = cluster_corpus(renamed, renamed_assessments)
    original_groups = {frozenset(cluster.member_role_ids) for cluster in clustering.clusters}
    mapped_groups = {
        frozenset({"alpha" if role_id == "x1" else "beta" if role_id == "x2" else "gamma" for role_id in cluster.member_role_ids})
        for cluster in renamed_clustering.clusters
    }
    assert original_groups == mapped_groups

    # Adding a similar finance neighbor is a corpus-level change, not a fixture branch.
    finance_peer = _synthetic_evidence("delta", title="Role D", organization="Org One", kind="finance_variant")
    expanded = evidences + [finance_peer]
    expanded_clustering = cluster_corpus(expanded, assessments + [_core_assessment("delta")])
    finance_group = expanded_clustering.cluster_for_role("gamma")
    assert finance_group is not None
    assert "delta" in finance_group.member_role_ids
    still_eng = expanded_clustering.cluster_for_role("alpha")
    assert still_eng is not None
    assert "delta" not in still_eng.member_role_ids


def test_same_independent_family_can_occupy_separate_clusters() -> None:
    result = build_architecture(load_corpus("corpus-a"))
    engineering_ids = {
        item.role_id for item in result.assessments if item.proposed_family == "engineering"
    }
    engineering_cluster_ids = {
        cluster.cluster_id
        for cluster in result.clusters
        if engineering_ids.intersection(cluster.member_role_ids)
    }
    assert len(engineering_cluster_ids) >= 2


def test_build_architecture_exposes_clustering_diagnostics() -> None:
    result = build_architecture(load_corpus("corpus-b"))
    assert result.clustering.signatures
    assert result.clusters is result.clustering.clusters
    assert result.unclustered_role_ids
    assert result.clustering.vectors
    assert {level.label for level in result.levels} >= {
        "IC1",
        "IC2",
        "IC3",
        "IC4",
        "IC5",
        "M1",
        "M2",
        "M3",
    }
    for cluster in result.clusters:
        assert cluster.cohesion >= 0
        if len(cluster.member_role_ids) > 1:
            assert cluster.label_confidence is None or 0 <= cluster.label_confidence <= 1


_GENERIC_JD = (
    "Partner with stakeholders to deliver team projects. Collaborate across the "
    "business. Responsible for supporting work. Direct reports and performance "
    "are discussed with the manager. Analysis and metrics are used when helpful."
)


def _craft_evidence(role_id: str, *, craft: str) -> RoleEvidence:
    shared = _GENERIC_JD
    if craft == "engineering_manager":
        distinctive = [
            "Implement and operate backend APIs for production HTTP services.",
            "Own on-call, pull requests, observability, and Kubernetes runbooks.",
            "Hire and coach a team of six engineers, including performance reviews. You have direct reports.",
        ]
        domain = "Backend APIs, service mesh, CI/CD, production HTTP services."
        people = (
            "This is a people-management role. You have direct reports. You hire, coach, "
            "and deliver performance ratings. You are the manager of record."
        )
    elif craft == "people_ops":
        distinctive = [
            "Handle employee-relations cases and advise hiring managers on workforce plans.",
            "Run talent acquisition requisitions, candidate pipelines, and calibration support.",
        ]
        domain = "HR business partner work, people programs, and workforce planning."
        people = "This is not a people-management role. You do not hire. None of those people report to you."
    elif craft == "data_science":
        distinctive = [
            "Own warehouse pipelines, analytic datasets, notebooks, and experimental design.",
            "Publish cohort definitions and ranking and matching models for analysts.",
        ]
        domain = "Applied statistics, notebooks, scoring jobs, and warehouse ingestion."
        people = "This is not a people-management role. You do not hire."
    elif craft == "finance":
        distinctive = [
            "Build forecast updates and explain variance versus plan for the operating plan.",
            "Own FP&A financial-modeling, the annual plan, and bottoms-up commentary.",
        ]
        domain = "Planning, forecasting, variance analysis, and corporate finance."
        people = "This is not a people-management role. You do not hire."
    elif craft == "product":
        distinctive = [
            "Own the product roadmap, problem briefs, discovery, and acceptance criteria.",
            "Prioritize the backlog and product outcomes for the product area.",
        ]
        domain = "Product direction, discovery, and roadmap trade-offs."
        people = "This is not a people-management role. You do not hire."
    else:
        distinctive = [
            "Own test coverage, integration tests, automated tests, and test harnesses.",
            "Build test doubles and keep production HTTP payments under test coverage.",
        ]
        domain = "Automated tests, test coverage, and integration tests for checkout."
        people = "This is not a people-management role. You do not hire."
    return RoleEvidence(
        role_id=role_id,
        title="Placeholder Title",
        organization="Example Co",
        team="Example",
        responsibilities=[*distinctive, shared],
        scope="Named book of work inside the function.",
        autonomy="Independent within published standards.",
        complexity="Day-to-day craft work with the usual trade-offs.",
        impact="Affects the named book of work.",
        leadership="Mentorship through review; no additional program ownership.",
        people_management=people,
        stakeholder_breadth="- Engineering\n- Product\n- Finance\n- People partners",
        domain_depth=domain,
        decision_making_authority="Local craft decisions; larger changes need review.",
        source_references=[SourceReference(document_id=role_id, locator="responsibilities")],
    )


def _cluster_pair(left: RoleEvidence, right: RoleEvidence):
    evidences = [left, right]
    assessments = [_core_assessment(item.role_id) for item in evidences]
    return cluster_corpus(evidences, assessments)


def test_generic_management_language_does_not_merge_people_and_engineering() -> None:
    clustering = _cluster_pair(
        _craft_evidence("eng-mgr", craft="engineering_manager"),
        _craft_evidence("hr-bp", craft="people_ops"),
    )
    left = clustering.cluster_for_role("eng-mgr")
    right = clustering.cluster_for_role("hr-bp")
    assert left is not None and right is not None
    assert set(left.member_role_ids) != set(right.member_role_ids)


def test_analysis_metrics_language_does_not_merge_finance_and_data() -> None:
    clustering = _cluster_pair(
        _craft_evidence("data-role", craft="data_science"),
        _craft_evidence("finance-role", craft="finance"),
    )
    left = clustering.cluster_for_role("data-role")
    right = clustering.cluster_for_role("finance-role")
    assert left is not None and right is not None
    assert set(left.member_role_ids) != set(right.member_role_ids)


def test_stakeholder_language_does_not_merge_product_and_qa() -> None:
    clustering = _cluster_pair(
        _craft_evidence("pm-role", craft="product"),
        _craft_evidence("qa-role", craft="qa"),
    )
    left = clustering.cluster_for_role("pm-role")
    right = clustering.cluster_for_role("qa-role")
    assert left is not None and right is not None
    assert set(left.member_role_ids) != set(right.member_role_ids)


def test_merged_roles_have_compatible_occupational_evidence() -> None:
    for corpus_id in ("corpus-a", "corpus-b"):
        result = build_architecture(load_corpus(corpus_id))
        by_id = {item.role_id: item for item in result.clustering.vectors}
        for cluster in result.clusters:
            for left_id, right_id in combinations(cluster.member_role_ids, 2):
                assert occupationally_compatible(by_id[left_id], by_id[right_id]), (
                    f"{left_id} merged with {right_id} without compatible occupational evidence"
                )


def test_hybrid_can_bridge_without_joining_a_core_cluster() -> None:
    result = build_architecture(load_corpus("corpus-b"))
    role_id = "mh-clinical-implementation-architect"
    assert role_id in result.unclustered_role_ids
    bridge = next(item for item in result.clustering.bridges if item.role_id == role_id)
    assert bridge.is_bridge
    assert bridge.nearest_cluster_id != bridge.alternative_cluster_id
