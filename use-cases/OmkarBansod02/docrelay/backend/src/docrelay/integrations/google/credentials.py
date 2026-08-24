import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class CredentialEncryptionError(ValueError):
    """Raised when an encrypted credential cannot be authenticated or decoded."""


class GoogleCredentialSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    access_token: SecretStr
    refresh_token: SecretStr
    token_type: str = "Bearer"
    scopes: tuple[str, ...] = Field(min_length=1)
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    ciphertext: str
    key_version: str


class CredentialCipher:
    """Versioned application-level authenticated encryption boundary.

    The database stores only Fernet ciphertext plus a non-secret key version. Key
    material is supplied by the process environment and never persisted here.
    """

    def __init__(self, keys: dict[str, Fernet], primary_version: str) -> None:
        if primary_version not in keys:
            raise CredentialEncryptionError("primary encryption key version is absent")
        self._keys = keys
        self.primary_version = primary_version

    @classmethod
    def from_json_keyring(cls, raw_keyring: str, primary_version: str) -> "CredentialCipher":
        try:
            values = json.loads(raw_keyring)
        except json.JSONDecodeError as exc:
            raise CredentialEncryptionError("encryption keyring must be valid JSON") from exc
        if not isinstance(values, dict) or not values:
            raise CredentialEncryptionError("encryption keyring must be a non-empty object")
        try:
            keys = {
                str(version): Fernet(str(key).encode("ascii")) for version, key in values.items()
            }
        except (ValueError, TypeError, UnicodeEncodeError) as exc:
            raise CredentialEncryptionError(
                "encryption keyring contains an invalid Fernet key"
            ) from exc
        return cls(keys, primary_version)

    def encrypt_json(self, *, context: str, payload: dict[str, Any]) -> EncryptedValue:
        envelope = {
            "schema": "docrelay.encrypted-secret.v1",
            "context": context,
            "payload": payload,
        }
        plaintext = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        token = self._keys[self.primary_version].encrypt(plaintext).decode("ascii")
        return EncryptedValue(ciphertext=token, key_version=self.primary_version)

    def decrypt_json(self, *, context: str, encrypted: EncryptedValue) -> dict[str, Any]:
        cipher = self._keys.get(encrypted.key_version)
        if cipher is None:
            raise CredentialEncryptionError("credential encryption key version is unavailable")
        try:
            plaintext = cipher.decrypt(encrypted.ciphertext.encode("ascii"))
            envelope = json.loads(plaintext)
        except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialEncryptionError("encrypted credential authentication failed") from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("schema") != "docrelay.encrypted-secret.v1"
            or envelope.get("context") != context
            or not isinstance(envelope.get("payload"), dict)
        ):
            raise CredentialEncryptionError("encrypted credential context is invalid")
        return cast(dict[str, Any], envelope["payload"])

    def encrypt_credentials(
        self, connection_id: UUID, credentials: GoogleCredentialSet
    ) -> EncryptedValue:
        return self.encrypt_json(
            context=f"google-connection:{connection_id}",
            payload={
                "access_token": credentials.access_token.get_secret_value(),
                "refresh_token": credentials.refresh_token.get_secret_value(),
                "token_type": credentials.token_type,
                "scopes": list(credentials.scopes),
                "access_token_expires_at": credentials.access_token_expires_at.isoformat(),
                "refresh_token_expires_at": (
                    credentials.refresh_token_expires_at.isoformat()
                    if credentials.refresh_token_expires_at
                    else None
                ),
            },
        )

    def decrypt_credentials(
        self, connection_id: UUID, encrypted: EncryptedValue
    ) -> GoogleCredentialSet:
        payload = self.decrypt_json(
            context=f"google-connection:{connection_id}", encrypted=encrypted
        )
        try:
            return GoogleCredentialSet.model_validate(payload)
        except (ValueError, TypeError) as exc:
            raise CredentialEncryptionError("decrypted credential payload is invalid") from exc

    def rotate(self, *, context: str, encrypted: EncryptedValue) -> EncryptedValue:
        payload = self.decrypt_json(context=context, encrypted=encrypted)
        return self.encrypt_json(context=context, payload=payload)
