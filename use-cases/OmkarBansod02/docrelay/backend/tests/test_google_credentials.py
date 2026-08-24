from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from docrelay.integrations.google.credentials import (
    CredentialCipher,
    CredentialEncryptionError,
    EncryptedValue,
    GoogleCredentialSet,
)


def _cipher(*, primary: str = "v1") -> CredentialCipher:
    keys = {
        "v1": Fernet.generate_key().decode("ascii"),
        "v2": Fernet.generate_key().decode("ascii"),
    }
    import json

    return CredentialCipher.from_json_keyring(json.dumps(keys), primary)


def test_credentials_are_authenticated_encrypted_and_context_bound() -> None:
    cipher = _cipher()
    connection_id = uuid4()
    credentials = GoogleCredentialSet(
        access_token=SecretStr("access-secret-value"),
        refresh_token=SecretStr("refresh-secret-value"),
        scopes=("openid", "https://www.googleapis.com/auth/drive.file"),
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    encrypted = cipher.encrypt_credentials(connection_id, credentials)

    assert encrypted.key_version == "v1"
    assert "access-secret-value" not in encrypted.ciphertext
    assert "refresh-secret-value" not in encrypted.ciphertext
    assert cipher.decrypt_credentials(connection_id, encrypted) == credentials
    with pytest.raises(CredentialEncryptionError):
        cipher.decrypt_credentials(uuid4(), encrypted)
    with pytest.raises(CredentialEncryptionError):
        cipher.decrypt_credentials(
            connection_id,
            EncryptedValue(
                ciphertext=f"{encrypted.ciphertext[:-1]}x",
                key_version=encrypted.key_version,
            ),
        )


def test_key_rotation_reencrypts_with_primary_without_plaintext_storage() -> None:
    import json

    keys = {
        "old": Fernet.generate_key().decode("ascii"),
        "current": Fernet.generate_key().decode("ascii"),
    }
    old_cipher = CredentialCipher.from_json_keyring(json.dumps(keys), "old")
    current_cipher = CredentialCipher.from_json_keyring(json.dumps(keys), "current")
    encrypted = old_cipher.encrypt_json(context="rotation-test", payload={"secret": "value"})

    rotated = current_cipher.rotate(context="rotation-test", encrypted=encrypted)

    assert rotated.key_version == "current"
    assert rotated.ciphertext != encrypted.ciphertext
    assert current_cipher.decrypt_json(context="rotation-test", encrypted=rotated) == {
        "secret": "value"
    }


def test_invalid_or_missing_keyring_fails_closed() -> None:
    with pytest.raises(CredentialEncryptionError):
        CredentialCipher.from_json_keyring("{}", "v1")
    with pytest.raises(CredentialEncryptionError):
        CredentialCipher.from_json_keyring('{"v1":"not-a-fernet-key"}', "v1")
    with pytest.raises(CredentialEncryptionError):
        CredentialCipher.from_json_keyring(
            '{"v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}', "missing"
        )
