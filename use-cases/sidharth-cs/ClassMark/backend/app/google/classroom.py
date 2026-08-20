"""Google Classroom API client — async httpx, Bearer token per call.

The access token is passed in by the caller (routes obtain a valid token
from the AuthStore); the client itself is stateless. All list methods
follow nextPageToken and return combined lists.

Endpoint map (official Google Classroom API docs):
- GET  /v1/courses                               courses.list
- GET  /v1/courses/{id}/courseWork               courses.courseWork.list
- GET  /v1/courses/{c}/courseWork/{w}/studentSubmissions   studentSubmissions.list
- GET  /v1/courses/{c}/courseWork/{w}/studentSubmissions/{s}   studentSubmissions.get
- POST /v1/courses/{c}/courseWork/{w}/studentSubmissions/{s}:modifyAttachments
- POST /v1/courses/{c}/courseWork/{w}/studentSubmissions/{s}:return
"""

from __future__ import annotations

import httpx

BASE_URL = "https://classroom.googleapis.com/v1"
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def submission_attachments(submission: dict) -> list[dict]:
    """The attachment list of a StudentSubmission resource.

    Official Classroom API contract (developers.google.com/classroom/
    reference/rest/v1/courses.courseWork.studentSubmissions): attachments
    live at `assignmentSubmission.attachments[]` for ASSIGNMENT-type
    coursework. Each Attachment is a union field with one of
    driveFile / youTubeVideo / link / form. The top-level `attachments`
    key is kept as a fallback only for defensive robustness against
    shape drift — the real key is `assignmentSubmission`.
    """
    assignment = submission.get("assignmentSubmission") or {}
    attachments = assignment.get("attachments") or submission.get("attachments") or []
    return attachments


class GoogleClassroomClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GoogleClassroomClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def list_courses(self, access_token: str) -> list[dict]:
        courses: list[dict] = []
        page_token = None
        while True:
            params: dict[str, object] = {"pageSize": 100, "courseStates": "ACTIVE"}
            if page_token:
                params["pageToken"] = page_token
            r = await self._client.get(
                "/courses", headers=self._headers(access_token), params=params
            )
            r.raise_for_status()
            data = r.json()
            courses.extend(data.get("courses", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return courses

    async def list_coursework(self, access_token: str, course_id: str) -> list[dict]:
        items: list[dict] = []
        page_token = None
        while True:
            params: dict[str, object] = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            r = await self._client.get(
                f"/courses/{course_id}/courseWork",
                headers=self._headers(access_token),
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("courseWork", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return items

    async def get_coursework(
        self, access_token: str, course_id: str, coursework_id: str
    ) -> dict:
        r = await self._client.get(
            f"/courses/{course_id}/courseWork/{coursework_id}",
            headers=self._headers(access_token),
        )
        r.raise_for_status()
        return r.json()

    async def create_coursework(
        self,
        access_token: str,
        course_id: str,
        *,
        title: str,
        description: str = "",
        work_type: str = "ASSIGNMENT",
        state: str = "PUBLISHED",
    ) -> dict:
        """courses.courseWork.create. CourseWork created through the API is
        associated with this Developer Console project
        (associatedWithDeveloper=true), which is what modifyAttachments
        requires — UI-created courseWork is not modifiable by the API."""
        r = await self._client.post(
            f"/courses/{course_id}/courseWork",
            headers=self._headers(access_token),
            json={
                "title": title,
                "description": description,
                "workType": work_type,
                "state": state,
            },
        )
        r.raise_for_status()
        return r.json()

    async def list_submissions(
        self, access_token: str, course_id: str, coursework_id: str
    ) -> list[dict]:
        items: list[dict] = []
        page_token = None
        while True:
            params: dict[str, object] = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            r = await self._client.get(
                f"/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions",
                headers=self._headers(access_token),
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("studentSubmissions", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return items

    async def get_submission(
        self, access_token: str, course_id: str, coursework_id: str, submission_id: str
    ) -> dict:
        r = await self._client.get(
            f"/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions/{submission_id}",
            headers=self._headers(access_token),
        )
        r.raise_for_status()
        return r.json()

    async def modify_attachments(
        self,
        access_token: str,
        course_id: str,
        coursework_id: str,
        submission_id: str,
        add_attachments: list[dict],
    ) -> dict:
        """Adds the reviewed Drive file to the SAME submission — the
        caller is responsible for passing the exact submission_id selected
        by the teacher (identity invariant enforced in the workflow layer,
        never inferred here)."""
        r = await self._client.post(
            f"/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions/{submission_id}:modifyAttachments",
            headers=self._headers(access_token),
            json={"addAttachments": add_attachments},
        )
        r.raise_for_status()
        return r.json()

    async def return_submission(
        self, access_token: str, course_id: str, coursework_id: str, submission_id: str
    ) -> dict:
        r = await self._client.post(
            f"/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions/{submission_id}:return",
            headers=self._headers(access_token),
            json={},
        )
        r.raise_for_status()
        return r.json()
