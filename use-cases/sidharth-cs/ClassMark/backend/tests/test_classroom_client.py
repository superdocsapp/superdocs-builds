"""Classroom API client tests — MockTransport, no network."""

import asyncio
import json

import httpx

from app.google.classroom import GoogleClassroomClient


def _client(handler) -> GoogleClassroomClient:
    c = GoogleClassroomClient()
    c._client = httpx.AsyncClient(
        base_url="https://classroom.googleapis.com/v1",
        transport=httpx.MockTransport(handler),
    )
    return c


def test_list_courses_sends_bearer_and_parses():
    seen = {}

    async def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200, json={"courses": [{"id": "c1", "name": "English", "section": "A"}]}
        )

    async def run():
        async with _client(handler) as c:
            courses = await c.list_courses("tok123")
        assert courses == [{"id": "c1", "name": "English", "section": "A"}]

    asyncio.run(run())
    assert seen["auth"] == "Bearer tok123"
    assert seen["params"]["courseStates"] == "ACTIVE"


def test_list_courses_follows_pagination():
    """nextPageToken must be followed and combined, not truncated."""

    async def handler(request):
        page = request.url.params.get("pageToken")
        if not page:
            return httpx.Response(
                200, json={"courses": [{"id": "c1"}], "nextPageToken": "p2"}
            )
        return httpx.Response(200, json={"courses": [{"id": "c2"}]})

    async def run():
        async with _client(handler) as c:
            courses = await c.list_courses("tok123")
        assert [c["id"] for c in courses] == ["c1", "c2"]

    asyncio.run(run())


def test_get_coursework_hits_exact_resource_path():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "id": "w1",
                "title": "Task 2B Feedback Demo",
                "workType": "ASSIGNMENT",
                "associatedWithDeveloper": True,
            },
        )

    async def run():
        async with _client(handler) as c:
            cw = await c.get_coursework("tok123", "c1", "w1")
        assert cw["id"] == "w1"
        assert cw["associatedWithDeveloper"] is True

    asyncio.run(run())
    assert seen["path"] == "/v1/courses/c1/courseWork/w1"


def test_create_coursework_posts_assignment_shape():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "w9",
                "title": "Task 2B API-Associated Feedback Demo",
                "workType": "ASSIGNMENT",
                "state": "PUBLISHED",
                "associatedWithDeveloper": True,
            },
        )

    async def run():
        async with _client(handler) as c:
            cw = await c.create_coursework(
                "tok123",
                "c1",
                title="Task 2B API-Associated Feedback Demo",
                description="desc",
            )
        assert cw["id"] == "w9"
        assert cw["associatedWithDeveloper"] is True

    asyncio.run(run())
    assert seen["path"] == "/v1/courses/c1/courseWork"
    assert seen["json"]["workType"] == "ASSIGNMENT"
    assert seen["json"]["state"] == "PUBLISHED"


def test_get_submission_hits_exact_resource_path():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "id": "s1",
                "userId": "u1",
                "state": "TURNED_IN",
                "attachments": [{"driveFile": {"id": "d1", "title": "essay.docx"}}],
            },
        )

    async def run():
        async with _client(handler) as c:
            sub = await c.get_submission("tok123", "c1", "w1", "s1")
        assert sub["id"] == "s1"
        assert sub["attachments"][0]["driveFile"]["id"] == "d1"

    asyncio.run(run())
    assert seen["path"] == "/v1/courses/c1/courseWork/w1/studentSubmissions/s1"


def test_modify_attachments_posts_to_modify_attachments_endpoint():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "s1",
                "attachments": [{"driveFile": {"id": "d1"}}, {"driveFile": {"id": "r1"}}],
            },
        )

    async def run():
        async with _client(handler) as c:
            resp = await c.modify_attachments(
                "tok123",
                "c1",
                "w1",
                "s1",
                add_attachments=[{"driveFile": {"id": "r1"}}],
            )
        attached = [a["driveFile"]["id"] for a in resp["attachments"]]
        assert attached == ["d1", "r1"]

    asyncio.run(run())
    assert seen["path"] == "/v1/courses/c1/courseWork/w1/studentSubmissions/s1:modifyAttachments"
    assert seen["json"] == {"addAttachments": [{"driveFile": {"id": "r1"}}]}


def test_return_submission_posts_to_return_endpoint():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"id": "s1", "state": "RETURNED"})

    async def run():
        async with _client(handler) as c:
            resp = await c.return_submission("tok123", "c1", "w1", "s1")
        assert resp["state"] == "RETURNED"

    asyncio.run(run())
    assert seen["path"] == "/v1/courses/c1/courseWork/w1/studentSubmissions/s1:return"


def test_404_raises_status_error():
    async def handler(request):
        return httpx.Response(404, json={"error": {"message": "Submission not found"}})

    async def run():
        async with _client(handler) as c:
            try:
                await c.get_submission("tok123", "c1", "w1", "missing")
            except httpx.HTTPStatusError as exc:
                assert exc.response.status_code == 404
                return
            raise AssertionError("expected httpx.HTTPStatusError")

    asyncio.run(run())
