from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.routes import router
from .config import Settings, load_settings
from .core.negotiation import NegotiationService
from .core.store import Store
from .slack.simulator import InMemoryMessenger
from .superdocs.client import SuperDocsClient
from .superdocs.fake import FakeSuperDocs
from .superdocs.transport import HTTPTransport, Transport


def build_service(settings: Settings) -> tuple[NegotiationService, Store]:
    store = Store(settings.database_path)
    transport: Transport
    if settings.fake_mode:
        transport = FakeSuperDocs()
    else:
        transport = HTTPTransport(settings.superdocs_base_url, settings.superdocs_api_key)
    client = SuperDocsClient(transport)
    # The REST/MCP surface is a machine interface; it does not post into real Slack.
    # A separate process running slack/bolt_app.py shares the same database_path and
    # SuperDocs session per deal, and uses SlackMessenger to post real Slack messages.
    messenger = InMemoryMessenger()
    service = NegotiationService(settings, store, client, messenger)
    return service, store


def create_app(service: NegotiationService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await service.recover_pending()
        yield

    app = FastAPI(title="Slack Redline Exchange", lifespan=lifespan)
    app.state.service = service
    app.include_router(router)
    return app


def main() -> FastAPI:
    settings = load_settings()
    service, _store = build_service(settings)
    return create_app(service)


app = main()
