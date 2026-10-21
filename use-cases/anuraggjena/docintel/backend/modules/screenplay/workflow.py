from backend.core.workflow.registry import workflow_registry
from backend.modules.screenplay.stages.parse import ParseStage
from backend.modules.screenplay.stages.format import FormatStage
from backend.modules.screenplay.stages.diff import DiffStage
from backend.modules.screenplay.schemas import ScreenplayWorkflowState
from backend.modules.screenplay.llm_config import get_screenplay_llm_provider
from backend.logging_config import get_logger

logger = get_logger(__name__)

SCREENPLAY_WORKFLOW_NAME = "screenplay"


def build_screenplay_stages(session=None, db_session=None):
    """
    Build screenplay workflow stage instances.

    When session or db_session is provided, returns stages with repositories wired to the active DB session.
    When None, returns minimal stage instances for registry metadata.
    """
    active_session = session if session is not None else db_session
    from backend.modules.screenplay.stages.parse import ParseStage
    from backend.modules.screenplay.stages.format import FormatStage
    from backend.modules.screenplay.stages.diff import DiffStage
    from backend.modules.screenplay.llm_config import get_screenplay_llm_provider

    llm = get_screenplay_llm_provider()
    parse_stage = ParseStage(llm_provider=llm)

    if active_session is not None:
        from backend.repositories.screenplay import FormattingItemRepository
        from backend.repositories.review import ReviewRepository
        from backend.repositories.workflow import WorkflowRunRepository

        formatting_item_repo = FormattingItemRepository(active_session)
        review_repo = ReviewRepository(active_session)
        run_repo = WorkflowRunRepository(active_session)

        format_stage = FormatStage(
            llm_provider=llm,
            formatting_item_repo=formatting_item_repo,
        )
        diff_stage = DiffStage(
            formatting_item_repo=formatting_item_repo,
            review_repo=review_repo,
            run_repo=run_repo,
        )
    else:
        format_stage = FormatStage(llm_provider=llm, formatting_item_repo=None)
        diff_stage = DiffStage(formatting_item_repo=None, review_repo=None, run_repo=None)

    return [parse_stage, format_stage, diff_stage]


def register_screenplay_workflow(
    formatting_item_repo=None,
    review_repo=None,
    run_repo=None,
) -> None:
    """Register the screenplay workflow with the global registry."""
    registered_names = [wf["name"] for wf in workflow_registry.list_workflows()]
    if SCREENPLAY_WORKFLOW_NAME in registered_names:
        logger.info("screenplay_workflow_already_registered")
        return

    stages = build_screenplay_stages(None)

    workflow_registry.register(
        workflow_name=SCREENPLAY_WORKFLOW_NAME,
        stages=stages,
        edges=[
            ("parse", "format"),
            ("format", "diff"),
            ("diff", "END"),
        ],
        state_schema=ScreenplayWorkflowState,
        description="Parses and formats screenplay documents with per-element review",
        configuration_schema={},
    )
    logger.info("screenplay_workflow_registered")

