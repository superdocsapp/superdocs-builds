import asyncio
import base64
import sys
import uuid
from datetime import datetime, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions

# Application-level services and models
from backend.app.database import AsyncSessionLocal
from backend.app.models import Dossier, DossierFinding, Document
from backend.app.services.ingestion import IngestionService
from backend.app.services.workflow import compile_diligence_workflow
from backend.app.exceptions import DuplicateFileError, FileIngestionError, UnsupportedFileError

# Initialize the MCP Server
server = Server("superdocs-diligence")

async def update_dossier_status(dossier_id: uuid.UUID, db) -> None:
    """Helper to update dossier status based on findings, matching backend logic."""
    res = await db.execute(
        select(DossierFinding).where(DossierFinding.dossier_id == dossier_id)
    )
    findings = res.scalars().all()
    if not findings:
        return

    statuses = {f.status for f in findings}
    review_statuses = {f.review_status for f in findings}

    res_d = await db.execute(select(Dossier).where(Dossier.id == dossier_id))
    dossier = res_d.scalar()
    if not dossier:
        return

    if "failed" in statuses:
        dossier.status = "failed"
    elif "pending" in review_statuses:
        dossier.status = "review_required"
    elif all(f.status in ("answered", "insufficient_evidence", "conflict") and f.review_status in ("approved", "rejected", "edited", "not_required") for f in findings):
        dossier.status = "completed"
    else:
        dossier.status = "running"
    
    dossier.updated_at = datetime.now(timezone.utc)
    db.add(dossier)
    await db.commit()

async def handle_list_tools(params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
    """Exposes exactly the four required SuperDocs machine integration tools."""
    return types.ListToolsResult(tools=[
        types.Tool(
            name="upload_document",
            description="Ingests a text, markdown, PDF, DOCX, or XLSX document into the startup due diligence data room.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string", 
                        "description": "Name of the file to ingest, e.g. 'financials.txt' or 'deck.pdf'"
                    },
                    "content_base64": {
                        "type": "string", 
                        "description": "Base64-encoded binary/text file contents"
                    }
                },
                "required": ["filename", "content_base64"]
            }
        ),
        types.Tool(
            name="send_edit_instruction",
            description="Submits reviewer manual answer and reasoning overrides to resolve a paused finding.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dossier_id": {"type": "string", "description": "Dossier UUID"},
                    "finding_id": {"type": "string", "description": "Finding UUID"},
                    "answer": {"type": "string", "description": "The final edited text answer to store"},
                    "reasoning_summary": {"type": "string", "description": "Notes outlining reasoning adjustments"}
                },
                "required": ["dossier_id", "finding_id", "answer", "reasoning_summary"]
            }
        ),
        types.Tool(
            name="approve_proposed_changes",
            description="Approves a proposed finding, clearing its review check and resuming graph thread finalization.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dossier_id": {"type": "string", "description": "Dossier UUID"},
                    "finding_id": {"type": "string", "description": "Finding UUID"}
                },
                "required": ["dossier_id", "finding_id"]
            }
        ),
        types.Tool(
            name="export_result",
            description="Exports the complete dossier report containing questions, answers, citations, and diligence gaps as Markdown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dossier_id": {"type": "string", "description": "Dossier UUID"}
                },
                "required": ["dossier_id"]
            }
        )
    ])

async def handle_call_tool(params: types.CallToolRequestParams) -> types.CallToolResult:
    """Routes tool execution requests and maps returns into structured JSON tool results."""
    name = params.name
    arguments = params.arguments or {}

    async with AsyncSessionLocal() as db:
        try:
            if name == "upload_document":
                filename = arguments.get("filename")
                content_base64 = arguments.get("content_base64")
                if not filename or not content_base64:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Filename and content_base64 are required"}))],
                        is_error=True
                    )

                try:
                    file_bytes = base64.b64decode(content_base64)
                except Exception:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Invalid Base64 payload"}))],
                        is_error=True
                    )

                ext = filename.lower().split(".")[-1]
                if ext not in ("txt", "md", "pdf", "docx", "xlsx", "csv"):
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": f"Unsupported file type: .{ext}"}))],
                        is_error=True
                    )

                try:
                    ingestion = IngestionService(db)
                    doc = await ingestion.ingest_document(filename, file_bytes)
                    await db.commit()
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({
                            "document_id": str(doc.id),
                            "filename": doc.filename,
                            "size": doc.file_size,
                            "hash": doc.hash_sha256,
                            "ingestion_status": "success",
                            "duplicate_status": False
                        }))]
                    )
                except DuplicateFileError as e:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({
                            "document_id": None,
                            "filename": filename,
                            "size": len(file_bytes),
                            "hash": None,
                            "ingestion_status": "duplicate",
                            "duplicate_status": True,
                            "error": str(e)
                        }))]
                    )
                except FileIngestionError as e:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({
                            "document_id": None,
                            "filename": filename,
                            "size": len(file_bytes),
                            "hash": None,
                            "ingestion_status": "failed",
                            "duplicate_status": False,
                            "error": str(e)
                        }))],
                        is_error=True
                    )

            elif name == "send_edit_instruction":
                d_id_str = arguments.get("dossier_id")
                f_id_str = arguments.get("finding_id")
                answer = arguments.get("answer")
                reasoning = arguments.get("reasoning_summary")

                try:
                    d_id = uuid.UUID(d_id_str)
                    f_id = uuid.UUID(f_id_str)
                except (ValueError, TypeError):
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Invalid UUID format"}))],
                        is_error=True
                    )

                res = await db.execute(select(DossierFinding).where(DossierFinding.id == f_id))
                finding = res.scalar()
                if not finding or finding.dossier_id != d_id:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Finding not found in the requested dossier"}))],
                        is_error=True
                    )

                if finding.review_status != "pending":
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Finding is not awaiting review"}))],
                        is_error=True
                    )

                # Run edit workflow integration
                workflow = compile_diligence_workflow(db.bind)
                config = {
                    "configurable": {
                        "thread_id": finding.workflow_thread_id,
                        "db": db,
                        "dossier_id": d_id,
                        "finding_id": f_id
                    }
                }
                
                await workflow.aupdate_state(config, {
                    "draft_answer": answer,
                    "reasoning_summary": reasoning,
                    "review_required": False
                })
                await workflow.ainvoke(None, config)

                finding.review_status = "edited"
                finding.answer = answer
                finding.reasoning_summary = reasoning
                if finding.status != "conflict":
                    finding.status = "answered"
                finding.completed_at = datetime.now(timezone.utc)
                db.add(finding)
                await db.commit()
                await db.refresh(finding)

                await update_dossier_status(d_id, db)

                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps({
                        "finding_id": str(finding.id),
                        "status": finding.status,
                        "review_status": finding.review_status,
                        "answer": finding.answer,
                        "reasoning_summary": finding.reasoning_summary
                    }))]
                )

            elif name == "approve_proposed_changes":
                d_id_str = arguments.get("dossier_id")
                f_id_str = arguments.get("finding_id")

                try:
                    d_id = uuid.UUID(d_id_str)
                    f_id = uuid.UUID(f_id_str)
                except (ValueError, TypeError):
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Invalid UUID format"}))],
                        is_error=True
                    )

                res = await db.execute(select(DossierFinding).where(DossierFinding.id == f_id))
                finding = res.scalar()
                if not finding or finding.dossier_id != d_id:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Finding not found in the requested dossier"}))],
                        is_error=True
                    )

                if finding.review_status != "pending":
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Finding is not awaiting review"}))],
                        is_error=True
                    )

                # Run approval workflow integration
                workflow = compile_diligence_workflow(db.bind)
                config = {
                    "configurable": {
                        "thread_id": finding.workflow_thread_id,
                        "db": db,
                        "dossier_id": d_id,
                        "finding_id": f_id
                    }
                }

                await workflow.aupdate_state(config, {"review_required": False})
                await workflow.ainvoke(None, config)

                finding.review_status = "approved"
                if finding.status != "conflict":
                    finding.status = "answered"
                finding.completed_at = datetime.now(timezone.utc)
                db.add(finding)
                await db.commit()
                await db.refresh(finding)

                await update_dossier_status(d_id, db)

                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps({
                        "finding_id": str(finding.id),
                        "status": finding.status,
                        "review_status": finding.review_status,
                        "approval_result": "success"
                    }))]
                )

            elif name == "export_result":
                d_id_str = arguments.get("dossier_id")
                try:
                    d_id = uuid.UUID(d_id_str)
                except (ValueError, TypeError):
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Invalid UUID format"}))],
                        is_error=True
                    )

                res = await db.execute(
                    select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == d_id)
                )
                dossier = res.scalar()
                if not dossier:
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": "Dossier not found"}))],
                        is_error=True
                    )

                # Format dossier findings identical to GET /api/v1/dossiers/{id}/export
                lines = []
                lines.append(f"# Diligence Dossier Report: {dossier.name}")
                lines.append(f"**Exported on (UTC)**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
                lines.append(f"**Overall Status**: {dossier.status.replace('_', ' ').title()}")
                lines.append(f"**Dossier ID**: {dossier.id}")
                lines.append("")

                lines.append("## Diligence Findings Summary")
                if not dossier.findings:
                    lines.append("*No findings exist in this dossier.*")
                else:
                    lines.append("| Question | Workflow Status | Governance Status | Confidence |")
                    lines.append("|---|---|---|---|")
                    for f in dossier.findings:
                        conf_str = f"{int(f.confidence * 100)}%" if f.confidence is not None else "N/A"
                        lines.append(f"| {f.question} | {f.status.upper()} | {f.review_status.upper()} | {conf_str} |")
                lines.append("")

                lines.append("## Detailed Findings and Evidence")
                for idx, f in enumerate(dossier.findings, 1):
                    lines.append(f"### {idx}. {f.question}")
                    lines.append(f"* **Workflow Status**: {f.status.replace('_', ' ').upper()}")
                    lines.append(f"* **Governance Status**: {f.review_status.replace('_', ' ').upper()}")
                    conf_str = f"{int(f.confidence * 100)}%" if f.confidence is not None else "N/A"
                    lines.append(f"* **Confidence Level**: {conf_str}")
                    lines.append(f"* **Answer**: {f.answer if f.answer else 'No answer generated.'}")
                    lines.append(f"* **Reasoning Summary**: {f.reasoning_summary if f.reasoning_summary else 'No reasoning summary provided.'}")
                    if f.review_reason:
                        lines.append(f"* **Reviewer Notes/Decision Details**: {f.review_reason}")
                    lines.append("")

                    if f.status == "insufficient_evidence":
                        lines.append("> [!WARNING]")
                        lines.append("> **Unresolved Diligence Gap**: Evidence was found to be insufficient to answer this question.")
                        lines.append("")

                    lines.append("#### Grounded Evidence:")
                    citations = f.citations or []
                    if not citations:
                        lines.append("*Evidence was not found in the data room documents.*")
                    else:
                        for cit in citations:
                            filename = cit.get("filename", "unknown_file")
                            sec = cit.get("section") or "N/A"
                            page = cit.get("page_number") or "N/A"
                            excerpt = cit.get("excerpt") or ""
                            lines.append(f"- **File**: `{filename}` | **Section**: `{sec}` | **Page**: `{page}`")
                            if excerpt:
                                lines.append(f"  *Excerpt*: \"{excerpt}\"")
                    lines.append("")
                    lines.append("---")
                    lines.append("")

                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="\n".join(lines))]
                )

            else:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": f"Unknown tool: {name}"}))],
                    is_error=True
                )

        except Exception as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps({"status": "error", "message": f"Database or runtime error: {str(e)}"}))],
                is_error=True
            )

# Register request handlers using official low-level SDK protocol mappings
server.add_request_handler("tools/list", types.ListToolsRequest.model_fields["params"].annotation, handle_list_tools)
server.add_request_handler("tools/call", types.CallToolRequest.model_fields["params"].annotation, handle_call_tool)

async def main():
    """Runs the stdio MCP server loop."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="superdocs-diligence",
                server_version="0.1.0",
                capabilities=server.get_capabilities(),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
