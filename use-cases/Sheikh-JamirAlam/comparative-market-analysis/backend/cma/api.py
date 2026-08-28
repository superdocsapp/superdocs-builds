import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .pipeline import branding_from_dict, generate_cma_from_saved_template, property_from_dict


class CMARequest(BaseModel):
    branding: dict[str, Any]
    subject: dict[str, Any]
    comps: list[dict[str, Any]] = Field(min_length=4)
    export_format: str = "pdf"


app = FastAPI(title="Comparative Market Analysis API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/generate-cma")
def generate_cma_endpoint(payload: CMARequest) -> dict[str, str]:
    if payload.export_format not in {"pdf", "docx", "html"}:
        raise HTTPException(
            status_code=422, detail="Unsupported export format")

    try:
        subject = property_from_dict(payload.subject)
        comps = [property_from_dict(comp) for comp in payload.comps]
        branding = branding_from_dict(payload.branding)
        output_dir = Path(__file__).resolve().parents[1] / "output"
        output_path = output_dir / f"cma_{uuid4().hex}.{payload.export_format}"
        template_path = Path(__file__).resolve(
        ).parents[1] / "templates" / "cma_saved_template.html"
        result = generate_cma_from_saved_template(
            subject,
            comps,
            branding,
            output_path,
            template_path=template_path,
            export_format=payload.export_format,
            api_key=os.getenv("SUPERDOCS_API_KEY"),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid CMA data: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Document generation failed: {exc}") from exc

    return {
        "message": "Document created successfully",
        "filename": result.name,
    }
