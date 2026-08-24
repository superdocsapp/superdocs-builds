"""
Toolkit abstraction for SuperDocs LangChain integration.
"""

from __future__ import annotations

from typing import List, Optional
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.dynamic import load_dynamic_superdocs_tools
from superdocs_langchain.tools import (
    ALL_SUPERDOCS_TOOLS,
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
    SuperDocsHistoryTool,
    SuperDocsListDocumentsTool,
    SuperDocsListSessionsTool,
    SuperDocsListTasksTool,
    SuperDocsRenderTemplateTool,
    SuperDocsSearchTool,
    SuperDocsSessionRevertTool,
)


class SuperDocsToolkit(BaseModel):
    """
    Toolkit containing standard or dynamically discovered SuperDocs tools
    ready to bind to LangChain agents and LangGraph state graphs.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: SuperDocsClient = Field(default_factory=SuperDocsClient)
    dynamic: bool = Field(
        default=False,
        description="Whether to bind tools dynamically from live server schemas."
    )
    include_task_tools: bool = Field(
        default=False,
        description="Whether to also include async task creation and job queue tools."
    )

    def get_tools(self) -> List[BaseTool]:
        """Return the list of configured LangChain tools for SuperDocs."""
        if self.dynamic:
            return load_dynamic_superdocs_tools(self.client)

        base_tools = [
            SuperDocsCreateDocumentTool(client=self.client),
            SuperDocsGetDocumentTool(client=self.client),
            SuperDocsEditSectionTool(client=self.client),
            SuperDocsSearchTool(client=self.client),
            SuperDocsRenderTemplateTool(client=self.client),
            SuperDocsExportDocumentTool(client=self.client),
            SuperDocsAddCommentTool(client=self.client),
            SuperDocsHistoryTool(client=self.client),
            SuperDocsChatTool(client=self.client),
            SuperDocsListSessionsTool(client=self.client),
            SuperDocsGetSessionHistoryTool(client=self.client),
            SuperDocsSessionRevertTool(client=self.client),
        ]

        if self.include_task_tools:
            base_tools.extend([
                SuperDocsCreateTaskTool(client=self.client),
                SuperDocsExecuteTaskTool(client=self.client),
                SuperDocsGetTaskStatusTool(client=self.client),
                SuperDocsListTasksTool(client=self.client),
                SuperDocsCancelTaskTool(client=self.client),
                SuperDocsListDocumentsTool(client=self.client),
            ])

        return base_tools
