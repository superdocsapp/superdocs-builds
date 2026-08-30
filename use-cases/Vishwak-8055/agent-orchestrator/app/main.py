"""FastAPI entrypoint. POST /agents/run for a single merged
response, POST /agents/stream for an SSE stream of per-agent
events -- the latter is what makes the UI feel alive while multiple
agents work in parallel instead of showing one long spinner.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.base import DocumentContext
from app.agents.evidence_factcheck import EvidenceFactCheckAgent
from app.agents.security_pii import SecurityPIIAgent
from app.agents.structure_dependency import StructureDependencyAgent
from app.agents.style_tone import StyleToneAgent
from app.orchestrator import Orchestrator

app = FastAPI(title="SuperDocs agent orchestrator")

orchestrator = Orchestrator(
    agents=[
        SecurityPIIAgent(),
        StyleToneAgent(),
        StructureDependencyAgent(),
        EvidenceFactCheckAgent(),
    ]
)


class RunRequest(BaseModel):
    selected_text: str
    command: str
    surrounding_text: str = ""


@app.post("/agents/run")
async def run_agents(payload: RunRequest):
    ctx = DocumentContext(
        selected_text=payload.selected_text,
        command=payload.command,
        surrounding_text=payload.surrounding_text,
    )
    response = await orchestrator.handle(ctx)
    return {
        "suggestion_count": response.suggestion_count,
        "results": [
            {
                "agent": r.agent_name,
                "ok": r.ok,
                "summary": r.summary,
                "error": r.error,
                "suggestions": [s.__dict__ for s in r.suggestions],
            }
            for r in response.results
        ],
    }


@app.post("/agents/stream")
async def stream_agents(payload: RunRequest):
    ctx = DocumentContext(
        selected_text=payload.selected_text,
        command=payload.command,
        surrounding_text=payload.surrounding_text,
    )

    async def event_source():
        async for event in orchestrator.stream(ctx):
            if event["event"] == "agent_result":
                r = event["result"]
                data = {
                    "event": "agent_result",
                    "agent": r.agent_name,
                    "ok": r.ok,
                    "summary": r.summary,
                    "suggestion_count": len(r.suggestions),
                }
            else:
                data = event
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok", "agents": [a.name for a in orchestrator.agents]}
