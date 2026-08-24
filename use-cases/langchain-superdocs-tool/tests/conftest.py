"""
Pytest fixtures for superdocs_langchain tests.
"""

import pytest
from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.toolkit import SuperDocsToolkit


@pytest.fixture
def client() -> SuperDocsClient:
    """Provides a clean in-memory offline SuperDocsClient instance."""
    return SuperDocsClient(offline=True)


@pytest.fixture
def populated_client() -> SuperDocsClient:
    """Provides an offline client with preloaded sample documents and sections."""
    c = SuperDocsClient(offline=True)
    c.create_document(
        title="Microservices Architecture Guide",
        content=(
            "# Architecture Overview\n"
            "High-level system design for distributed microservices.\n\n"
            "## Service Mesh\n"
            "Details on mTLS and Envoy proxy routing.\n\n"
            "## Observability\n"
            "OpenTelemetry traces, Prometheus metrics, and structured logs."
        ),
        folder="engineering",
        metadata={"tags": ["architecture", "microservices", "backend"]},
    )
    c.create_document(
        title="Database Sharding Strategy",
        content=(
            "# Database Sharding\n"
            "Partitioning relational databases for horizontal scaling.\n\n"
            "## Consistent Hashing\n"
            "Ring topology for distributed keyspace distribution."
        ),
        folder="database",
        metadata={"tags": ["database", "scaling"]},
    )
    return c


@pytest.fixture
def toolkit(client: SuperDocsClient) -> SuperDocsToolkit:
    """Provides a standard SuperDocsToolkit."""
    return SuperDocsToolkit(client=client)
