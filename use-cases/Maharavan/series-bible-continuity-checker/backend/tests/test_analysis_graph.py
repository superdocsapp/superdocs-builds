import pytest

from series_bible.application.analysis_graph import build_analysis_graph


@pytest.mark.asyncio
async def test_analysis_graph_executes_required_stages_in_order():
    observed = []
    stages = (
        "INGEST",
        "EXTRACT_FACTS",
        "VALIDATE_FACTS",
        "BUILD_OR_UPDATE_BIBLE",
        "RETRIEVE_RELEVANT_FACTS",
        "CHECK_CONTINUITY",
        "CLASSIFY_FINDINGS",
        "PERSIST_FINDINGS",
    )

    def node(stage):
        async def execute(state):
            observed.append(stage)
            return {"completed_stages": [*state.get("completed_stages", []), stage]}
        return execute

    graph = build_analysis_graph({stage: node(stage) for stage in stages})
    result = await graph.ainvoke({"run_id": "run", "series_id": "series"})
    assert observed == list(stages)
    assert result["completed_stages"] == list(stages)