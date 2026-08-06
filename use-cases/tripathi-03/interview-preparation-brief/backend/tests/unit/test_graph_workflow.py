"""Unit tests for LangGraph workflow wiring."""

from app.agents.graph import NODE_ORDER, build_brief_graph, build_validated_brief_graph


def test_node_order():
    assert NODE_ORDER == [
        "ResumeParser",
        "JDParser",
        "CompanyResearch",
        "SkillGapAnalysis",
        "QuestionGeneration",
        "AnswerGeneration",
        "InterviewPreparationReport",
    ]


def test_graph_contains_all_nodes():
    graph = build_brief_graph()
    names = set(graph.get_graph().nodes)
    for node in NODE_ORDER:
        assert node in names


def test_validated_graph_contains_all_nodes():
    graph = build_validated_brief_graph()
    names = set(graph.get_graph().nodes)
    for node in NODE_ORDER:
        assert node in names
