"""
SuperDocs LangChain & LangGraph Integration Package.
"""

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.dynamic import (
    build_dynamic_tool,
    load_dynamic_superdocs_tools,
    load_tools_from_mcp_manifest,
)
from superdocs_langchain.models import (
    AccountWhoamiResponse,
    AgentTask,
    ApprovalMode,
    DocumentChanges,
    DocumentComment,
    DocumentSection,
    DocumentState,
    DocumentVersion,
    EditorAction,
    ExportFormat,
    ModelTier,
    SearchResult,
    SectionEditMode,
    SessionHistoryResponse,
    SessionMessage,
    SessionRevertResponse,
    SessionSummary,
    SuperDocsChatResponse,
    SuperDocsJob,
    SuperDocsUsage,
    SuperDocument,
    TaskStatus,
    TemplateDefinition,
    ThinkingDepth,
    ToolResponse,
)
from superdocs_langchain.toolkit import SuperDocsToolkit
from superdocs_langchain.tools import (
    SuperDocsAddCommentTool,
    SuperDocsCancelTaskTool,
    SuperDocsChatTool,
    SuperDocsCreateDocumentTool,
    SuperDocsCreateTaskTool,
    SuperDocsEditSectionTool,
    SuperDocsExecuteTaskTool,
    SuperDocsExportDocumentTool,
    SuperDocsGetDocumentTool,
    SuperDocsGetSessionHistoryTool,
    SuperDocsGetTaskStatusTool,
    SuperDocsListDocumentsTool,
    SuperDocsListTasksTool,
    SuperDocsRenderTemplateTool,
    SuperDocsSearchTool,
)

from superdocs_langchain.planner import DynamicTaskPlan, DynamicTaskPlanner, TaskPlanItem
from superdocs_langchain.dynamic_agent import DynamicAgentState, create_dynamic_planner_agent

# Aliases for backward compatibility
SuperDocsCommentTool = SuperDocsAddCommentTool
SuperDocsExportTool = SuperDocsExportDocumentTool
SuperDocsHistoryTool = SuperDocsGetSessionHistoryTool
SuperDocsListSessionsTool = SuperDocsListDocumentsTool
SuperDocsTemplateRenderTool = SuperDocsRenderTemplateTool
SuperDocsSessionHistoryTool = SuperDocsGetSessionHistoryTool

__all__ = [
    "SuperDocsClient",
    "SuperDocsToolkit",
    "SuperDocsChatTool",
    "SuperDocsCreateTaskTool",
    "SuperDocsExecuteTaskTool",
    "SuperDocsGetTaskStatusTool",
    "SuperDocsListTasksTool",
    "SuperDocsCancelTaskTool",
    "SuperDocsExportDocumentTool",
    "SuperDocsListDocumentsTool",
    "SuperDocsGetSessionHistoryTool",
    "SuperDocsCreateDocumentTool",
    "SuperDocsGetDocumentTool",
    "SuperDocsEditSectionTool",
    "SuperDocsSearchTool",
    "SuperDocsRenderTemplateTool",
    "SuperDocsAddCommentTool",
    "SuperDocsCommentTool",
    "SuperDocsExportTool",
    "SuperDocsHistoryTool",
    "SuperDocsListSessionsTool",
    "SuperDocsTemplateRenderTool",
    "SuperDocsSessionHistoryTool",
    "load_dynamic_superdocs_tools",
    "build_dynamic_tool",
    "load_tools_from_mcp_manifest",
    "SuperDocument",
    "DocumentSection",
    "DocumentVersion",
    "DocumentComment",
    "SearchResult",
    "TemplateDefinition",
    "ToolResponse",
    "ExportFormat",
    "SectionEditMode",
    "AgentTask",
    "TaskStatus",
    "ModelTier",
    "ThinkingDepth",
    "ApprovalMode",
    "SuperDocsJob",
    "SuperDocsChatResponse",
    "SuperDocsUsage",
    "DocumentChanges",
    "AccountWhoamiResponse",
    "SessionMessage",
    "DocumentState",
    "SessionSummary",
    "SessionHistoryResponse",
    "SessionRevertResponse",
    "EditorAction",
    "PlanApprovalState",
    "TaskPlanItem",
    "DynamicTaskPlan",
    "DynamicTaskPlanner",
    "DynamicAgentState",
    "create_dynamic_planner_agent",
]
