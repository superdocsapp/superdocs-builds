from io import BytesIO
from zipfile import ZipFile
from fastapi.responses import StreamingResponse
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import Base, engine, get_db
from models import Project
from schemas import ProjectCreate, ProjectResponse
from document_generator import generate_documents as generate_governance_documents


Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="DocTask API",
    version="0.1.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProjectDetails(BaseModel):
    project_name: str
    license: str
    governance_model: str
    contact_email: EmailStr


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "doctask-api"
    }


@app.post("/api/generate")
def generate_documents_api(data: ProjectDetails):
    return {
        "status": "success",
        "message": "Document generation request accepted.",
        "project": data.project_name,
        "documents": [
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "MAINTAINERS.md",
            "CLA.md",
            "RELEASE_POLICY.md",
        ],
    }

@app.get("/api/projects", response_model=list[ProjectResponse])
def get_projects(
    db: Session = Depends(get_db)
):
    projects = db.query(Project).all()

    return projects
@app.post("/api/projects", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db)
):
    try:
        existing_project = db.query(Project).filter(
            Project.name == project.name
        ).first()

        if existing_project:
            raise HTTPException(
                status_code=409,
                detail="A project with this name already exists."
            )

        new_project = Project(
            name=project.name,
            license=project.license,
            governance_model=project.governance_model,
            contact_email=project.contact_email
        )

        db.add(new_project)
        db.commit()
        db.refresh(new_project)

        return new_project

    except HTTPException:
        raise

    except Exception as e:
        db.rollback()

        print("CREATE PROJECT ERROR:", repr(e))

        raise HTTPException(
            status_code=500,
            detail="Unable to create project."
        )

@app.post("/api/projects/{project_id}/generate")
def generate_project_documents(
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = db.query(Project).filter(
            Project.id == project_id
        ).first()

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found"
            )

        generated_documents = generate_governance_documents(project)

        return {
            "message": "Documents generated successfully",
            "project_id": project.id,
            "project_name": project.name,
            "documents": generated_documents
        }

    except HTTPException:
        raise

    except Exception as e:
        print("GENERATE ERROR:", repr(e))

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# -----------------------------
# Delete Project
# -----------------------------
@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db)
):
    project = db.query(Project).filter(
        Project.id == project_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    db.delete(project)
    db.commit()

    return {
        "message": "Project deleted successfully",
        "project_id": project_id
    }
@app.get("/api/projects/{project_id}/download")
def download_project_documents(
    project_id: int,
    db: Session = Depends(get_db)
):
    try:
        project = db.query(Project).filter(
            Project.id == project_id
        ).first()

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found"
            )

        generated_documents = generate_governance_documents(project)

        zip_buffer = BytesIO()

        with ZipFile(zip_buffer, "w") as zip_file:
            for document in generated_documents:
                zip_file.writestr(
                    document["filename"],
                    document["content"]
                )

        zip_buffer.seek(0)

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{project.name}_governance_pack.zip"'
                )
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        print("DOWNLOAD ZIP ERROR:", repr(e))

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )