from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Financial Close Pack API"

    # CORS. The dev server runs on 5180 (see frontend/package.json and vite.config.ts).
    frontend_origin: str = "http://localhost:5180"
    additional_cors_origins: str = ""

    # Session signing. Left blank, a durable secret is created under storage_dir so
    # tokens survive restarts and stay valid across multiple uvicorn workers.
    session_secret: str = ""
    session_ttl_seconds: int = 43_200

    # Persistence. sqlite:// runs the stdlib driver (what the tests use); postgresql://
    # runs psycopg3 against Neon or any other Postgres.
    database_url: str = "sqlite:///./var/close_pack.db"
    neon_database_url: str = ""
    storage_dir: str = "./var/storage"

    # Object storage. Any S3-compatible endpoint (Storj, R2, AWS). Left blank, uploads
    # and exports fall back to storage_dir on local disk.
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "us-1"

    # Clerk. With a secret key set, bearer tokens are verified as Clerk session JWTs and
    # the demo-session endpoint is refused.
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    # The frontend's copy is the one that actually gets set in .env; read it too so the
    # backend can derive the Clerk instance domain without a second variable.
    vite_clerk_publishable_key: str = ""

    # How long a `generating` flag is believed before it is treated as abandoned by a
    # crashed worker. Must exceed a real run: uploads are 60s each and the edit call is
    # 180s, so a full pack cannot legitimately take this long.
    generation_timeout_seconds: int = 900

    # SuperDocs. "mock" runs the deterministic in-process client, "live" calls the REST API.
    superdocs_mode: str = "mock"
    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app/v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        origins = [
            self.frontend_origin.strip(),
            "http://localhost:5180",
            "http://127.0.0.1:5180",
        ]
        origins.extend(o.strip() for o in self.additional_cors_origins.split(",") if o.strip())
        deduped: list[str] = []
        for origin in origins:
            if origin and origin not in deduped:
                deduped.append(origin)
        return deduped

    @property
    def resolved_database_url(self) -> str:
        """NEON_DATABASE_URL wins when set, so switching backends is one env var.

        A blank DATABASE_URL must fall back to the sqlite default rather than
        overriding it with an empty string.
        """
        return (
            self.neon_database_url.strip()
            or self.database_url.strip()
            or "sqlite:///./var/close_pack.db"
        )

    @property
    def is_postgres(self) -> bool:
        return self.resolved_database_url.startswith(("postgres://", "postgresql://"))

    @property
    def sqlite_path(self) -> str:
        url = self.resolved_database_url
        if not url.startswith("sqlite:"):
            raise RuntimeError(
                f"sqlite_path read while DATABASE_URL is {url.split('://', 1)[0]!r}. "
                "This is a bug: check settings.is_postgres before using it."
            )
        return url.split("sqlite:///", 1)[-1] if "sqlite:///" in url else url.split("sqlite:", 1)[-1]

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint_url and self.s3_access_key_id and self.s3_bucket_name)

    @property
    def clerk_enabled(self) -> bool:
        return bool(self.clerk_secret_key and self.clerk_domain)

    @property
    def clerk_domain(self) -> str:
        """The Clerk instance domain, decoded from the publishable key.

        A publishable key is `pk_test_<base64 of "domain$">`, so the JWKS endpoint and
        the expected token issuer both fall out of it and need no extra configuration.
        """
        import base64
        import binascii

        key = (self.clerk_publishable_key or self.vite_clerk_publishable_key).strip()
        if not key.startswith(("pk_test_", "pk_live_")):
            return ""
        payload = key.split("_", 2)[-1]
        try:
            decoded = base64.b64decode(payload + "=" * (-len(payload) % 4)).decode("ascii")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return ""
        domain = decoded.rstrip("$").strip()
        # Guard against a malformed key turning into an attacker-chosen JWKS host.
        return domain if domain and "/" not in domain and " " not in domain else ""

    @property
    def clerk_issuer(self) -> str:
        return f"https://{self.clerk_domain}" if self.clerk_domain else ""

    @property
    def clerk_jwks_url(self) -> str:
        return f"{self.clerk_issuer}/.well-known/jwks.json" if self.clerk_domain else ""


settings = Settings()
