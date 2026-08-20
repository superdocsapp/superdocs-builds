"""Read-only Classroom browsing: courses, coursework, submissions.

The browser-facing selectors. Each route resolves the session's access
token server-side and proxies the Google call — the token never leaves the
backend.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.routes_auth import require_auth
from app.google.classroom import submission_attachments

router = APIRouter()


def _classroom(request: Request):
    return request.app.state.classroom_client


@router.get("/api/classroom/courses")
async def list_courses(request: Request):
    token = await require_auth(request)
    try:
        courses = await _classroom(request).list_courses(token)
    except Exception as exc:
        raise HTTPException(502, f"Classroom API failed: {exc}") from exc
    return [
        {"id": c.get("id"), "name": c.get("name"), "section": c.get("section", "")}
        for c in courses
    ]


@router.get("/api/classroom/courses/{course_id}/coursework")
async def list_coursework(course_id: str, request: Request):
    token = await require_auth(request)
    try:
        items = await _classroom(request).list_coursework(token, course_id)
    except Exception as exc:
        raise HTTPException(502, f"Classroom API failed: {exc}") from exc
    return [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "state": c.get("state"),
            "dueDate": c.get("dueDate"),
        }
        for c in items
    ]


@router.get("/api/classroom/courses/{course_id}/coursework/{coursework_id}/submissions")
async def list_submissions(course_id: str, coursework_id: str, request: Request):
    token = await require_auth(request)
    try:
        items = await _classroom(request).list_submissions(token, course_id, coursework_id)
    except Exception as exc:
        raise HTTPException(502, f"Classroom API failed: {exc}") from exc
    return [
        {
            "id": s.get("id"),
            "userId": s.get("userId"),
            "state": s.get("state"),
            "courseWorkId": s.get("courseWorkId"),
            "attachments": [
                {
                    "driveFile": a.get("driveFile"),
                    "link": a.get("link"),
                    "youTubeVideo": a.get("youTubeVideo"),
                }
                for a in submission_attachments(s)
            ],
        }
        for s in items
    ]
