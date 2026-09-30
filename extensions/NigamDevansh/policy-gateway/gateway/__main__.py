from __future__ import annotations

import uvicorn

from gateway.app import create_app
from gateway.settings import get_settings


def main() -> None:
    settings = get_settings()
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=settings.listen_port)


if __name__ == "__main__":
    main()
