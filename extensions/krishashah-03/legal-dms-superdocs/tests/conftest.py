import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.dms.seed import build_seeded_store
from app.routers.documents import register_routes
from app.services.workflow import DocumentWorkflow
from tests.mocks import FakeSuperDocsClient


@pytest.fixture
def dms_store():
    return build_seeded_store()


@pytest.fixture
def fake_superdocs():
    return FakeSuperDocsClient()


@pytest.fixture
def workflow(dms_store, fake_superdocs):
    return DocumentWorkflow(dms_store, fake_superdocs)


@pytest.fixture
def api_client(dms_store, fake_superdocs, workflow):
    """A FastAPI TestClient wired to the SAME dms_store/fake_superdocs/workflow
    instances the test itself holds, so a test can checkout via HTTP and then
    inspect internal state directly (or vice versa)."""
    app = FastAPI()
    router = APIRouter()
    register_routes(
        router,
        get_dms=lambda: dms_store,
        get_superdocs=lambda: fake_superdocs,
        get_workflow=lambda: workflow,
    )
    app.include_router(router)
    return TestClient(app)
