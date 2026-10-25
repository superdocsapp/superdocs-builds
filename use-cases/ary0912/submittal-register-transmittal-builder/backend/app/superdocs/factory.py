from app.core.config import settings
from app.superdocs.http_client import (
    SuperDocsHTTPClient,
)
from app.superdocs.mock_client import (
    MockSuperDocsClient,
)


_mock_client: MockSuperDocsClient | None = None
_http_client: SuperDocsHTTPClient | None = None


def get_superdocs_client():

    global _mock_client, _http_client

    if settings.app_env == "test":

        if _mock_client is None:
            _mock_client = MockSuperDocsClient()
        return _mock_client

    if not settings.superdocs_api_key:

        raise RuntimeError(
            "SUPERDOCS_API_KEY is required "
            "outside test mode."
        )

    if _http_client is None:
        _http_client = SuperDocsHTTPClient()
    return _http_client
