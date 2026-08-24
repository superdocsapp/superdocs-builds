"""Optional Locust load test (nicer UI/reporting than the async script).

Run:
    export API_KEY=<a tenant key from POST /v1/admin/tenants>
    locust -f loadtests/locustfile.py --host http://localhost:8000

Then open http://localhost:8089. Uses read endpoints by default so it does not
consume SuperDocs operations.
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task


class GatewayUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.headers = {"Authorization": f"Bearer {os.environ.get('API_KEY', '')}"}

    @task(3)
    def list_documents(self) -> None:
        self.client.get("/v1/documents", headers=self.headers, name="GET /v1/documents")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")
