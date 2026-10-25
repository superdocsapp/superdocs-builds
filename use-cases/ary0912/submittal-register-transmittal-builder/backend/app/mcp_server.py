"""Model Context Protocol (MCP) Server for DocTask.

Exposes DocTask operations as machine-callable tools for automated agents and IDEs.
Complies with Model Context Protocol standards.
"""

import json
import sys
from datetime import date
from typing import Any

from app.db.session import SessionLocal
from app.models.finding import Finding
from app.models.submittal import Submittal
from app.models.transmittal import Transmittal
from app.services.register import (
    generate_register,
    get_overdue_submittals,
    get_register,
    update_register_status,
    update_submittal_status,
)
from app.services.review import review_finding as review_finding_service
from app.services.search_chat import chat_project, search_project


TOOLS = [
    {
        "name": "list_submittals",
        "description": "List all submittal register items for a project with their review and register status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID (e.g. BROD-2026)"}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_submittal_detail",
        "description": "Get complete details for a submittal including comparison findings, evidence, and transmittal status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "submittal_number": {"type": "string", "description": "Submittal number (e.g. SUB-001)"}
            },
            "required": ["submittal_number"],
        },
    },
    {
        "name": "review_finding",
        "description": "Apply a human review decision (APPROVE, REJECT, or REQUEST_CLARIFICATION) to a submittal finding.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "UUID of the finding"},
                "reviewer": {"type": "string", "description": "Name/identifier of the reviewer"},
                "decision": {
                    "type": "string",
                    "enum": ["APPROVE", "REJECT", "REQUEST_CLARIFICATION"],
                    "description": "Review decision",
                },
                "comment": {"type": "string", "description": "Optional reviewer notes/justification"},
            },
            "required": ["finding_id", "reviewer", "decision"],
        },
    },
    {
        "name": "get_overdue_submittals",
        "description": "Get all submittals whose due date has passed and remain unreviewed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "search_project",
        "description": "Search across submittals, comparison findings, specifications, and transmittals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "query": {"type": "string", "description": "Search query keyword"},
            },
            "required": ["project_id", "query"],
        },
    },
    {
        "name": "chat_project",
        "description": "Ask an evidence-grounded contextual question about specifications, findings, deviations, or overdue items.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "query": {"type": "string", "description": "User question"},
                "context_submittal_number": {"type": "string", "description": "Optional submittal number context"},
            },
            "required": ["project_id", "query"],
        },
    },
]


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        if name == "list_submittals":
            items = get_register(db, arguments["project_id"])
            return {
                "items": [
                    {
                        "number": i.number,
                        "title": i.title,
                        "specification_section": i.specification_section,
                        "register_status": i.register_status,
                        "status": i.status,
                        "due_date": str(i.due_date) if i.due_date else None,
                    }
                    for i in items
                ]
            }

        elif name == "get_submittal_detail":
            s = db.query(Submittal).filter(Submittal.number == arguments["submittal_number"]).first()
            if not s:
                return {"error": f"Submittal {arguments['submittal_number']} not found."}
            findings = db.query(Finding).filter(Finding.submittal_id == s.id).all()
            return {
                "number": s.number,
                "title": s.title,
                "specification_section": s.specification_section,
                "register_status": s.register_status,
                "status": s.status,
                "findings": [
                    {
                        "id": f.id,
                        "attribute": f.attribute,
                        "requirement": f.requirement,
                        "submitted_value": f.submitted_value,
                        "result": f.result,
                        "specification_evidence": f.specification_evidence,
                        "submission_evidence": f.submission_evidence,
                        "status": f.status,
                        "reviewer": f.reviewer,
                        "reviewer_comment": f.reviewer_comment,
                    }
                    for f in findings
                ],
            }

        elif name == "review_finding":
            finding = review_finding_service(
                db=db,
                finding_id=arguments["finding_id"],
                reviewer=arguments["reviewer"],
                decision=arguments["decision"],
                comment=arguments.get("comment"),
            )
            update_submittal_status(db, finding.submittal_id)
            return {
                "finding_id": finding.id,
                "status": finding.status,
                "reviewer": finding.reviewer,
                "comment": finding.reviewer_comment,
            }

        elif name == "get_overdue_submittals":
            items = get_overdue_submittals(db, arguments["project_id"], date.today())
            return {
                "overdue_count": len(items),
                "items": [
                    {
                        "number": i.number,
                        "title": i.title,
                        "specification_section": i.specification_section,
                        "required_by": i.required_by,
                        "due_date": str(i.due_date),
                    }
                    for i in items
                ],
            }

        elif name == "search_project":
            res = search_project(db, arguments["project_id"], arguments["query"])
            return res.model_dump()

        elif name == "chat_project":
            res = chat_project(
                db,
                arguments["project_id"],
                arguments["query"],
                arguments.get("context_submittal_number"),
            )
            return res.model_dump()

        else:
            return {"error": f"Unknown tool: {name}"}
    finally:
        db.close()


def run_stdio_server():
    """Run JSON-RPC stdio loop for MCP clients."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            msg_id = req.get("id")
            method = req.get("method")

            if method == "tools/list":
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
            elif method == "tools/call":
                params = req.get("params", {})
                tool_name = params.get("name")
                args = params.get("arguments", {})
                result = handle_tool_call(tool_name, args)
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            else:
                resp = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}}

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err_resp = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
