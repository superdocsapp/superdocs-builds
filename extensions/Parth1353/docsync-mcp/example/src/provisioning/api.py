"""The provisioning HTTP surface.

Part of a synthetic example service. No real company's code.

The route table is a plain mapping rather than a pile of decorators so that a
single regex capture yields the whole route — method and path in one string,
which is what the documentation quotes. See docsync.yaml, fact
``api.endpoints``, and the README's note on why a list fact is one capture
group rather than several.
"""

from __future__ import annotations

ROUTES: dict[str, str] = {
    "GET /v1/circuits": "list_circuits",
    "POST /v1/circuits": "create_circuit",
    "GET /v1/circuits/{circuit_id}": "get_circuit",
    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",
}
