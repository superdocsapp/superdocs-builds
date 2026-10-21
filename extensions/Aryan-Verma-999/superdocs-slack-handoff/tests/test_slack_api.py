import asyncio
import unittest

import httpx

from app import SlackApi


class SlackApiTests(unittest.TestCase):
    def test_file_lookup_uses_documented_get_and_file_query_parameter(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "file": {"id": "F12345678"}})

        async def exercise():
            async with httpx.AsyncClient(base_url="https://slack.com/api/", headers={"Authorization": "Bearer test"}, transport=httpx.MockTransport(handler)) as client:
                api = SlackApi("test", client=client)
                file = await api.file("F12345678")
                self.assertEqual(file["id"], "F12345678")

        asyncio.run(exercise())
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].url.path, "/api/files.info")
        self.assertEqual(seen[0].url.params["file"], "F12345678")

    def test_export_reservation_uses_documented_get_and_scalar_parameters(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "upload_url": "https://uploads.slack.test/upload", "file_id": "F12345678"})

        async def exercise():
            async with httpx.AsyncClient(base_url="https://slack.com/api/", headers={"Authorization": "Bearer test"}, transport=httpx.MockTransport(handler)) as client:
                api = SlackApi("test", client=client)
                self.assertEqual(await api.reserve_upload("review.pdf", 12), ("https://uploads.slack.test/upload", "F12345678"))

        asyncio.run(exercise())
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].url.path, "/api/files.getUploadURLExternal")
        self.assertEqual(dict(seen[0].url.params), {"filename": "review.pdf", "length": "12"})


if __name__ == "__main__":
    unittest.main()
