import hashlib
import hmac
import time

from app.clients.box_client import verify_box_webhook_signature

PRIMARY = "primary-secret"
SECONDARY = "secondary-secret"


def sign(body: bytes, timestamp: str, key: str) -> str:
    return hmac.new(key.encode(), body + timestamp.encode(), hashlib.sha256).hexdigest()


def test_valid_primary_signature_accepted():
    body = b'{"trigger":"FILE.UPLOADED"}'
    ts = str(time.time())
    sig = sign(body, ts, PRIMARY)
    headers = {
        "BOX-DELIVERY-TIMESTAMP": ts,
        "BOX-SIGNATURE-PRIMARY": sig,
        "BOX-SIGNATURE-SECONDARY": "",
    }
    assert verify_box_webhook_signature(body, headers, PRIMARY, SECONDARY) is True


def test_valid_secondary_signature_accepted_for_key_rotation():
    body = b'{"trigger":"FILE.UPLOADED"}'
    ts = str(time.time())
    sig = sign(body, ts, SECONDARY)
    headers = {
        "BOX-DELIVERY-TIMESTAMP": ts,
        "BOX-SIGNATURE-PRIMARY": "wrong",
        "BOX-SIGNATURE-SECONDARY": sig,
    }
    assert verify_box_webhook_signature(body, headers, PRIMARY, SECONDARY) is True


def test_tampered_body_rejected():
    body = b'{"trigger":"FILE.UPLOADED"}'
    ts = str(time.time())
    sig = sign(body, ts, PRIMARY)
    headers = {"BOX-DELIVERY-TIMESTAMP": ts, "BOX-SIGNATURE-PRIMARY": sig}
    tampered_body = b'{"trigger":"FILE.DELETED"}'
    assert verify_box_webhook_signature(tampered_body, headers, PRIMARY, SECONDARY) is False


def test_stale_timestamp_rejected_replay_protection():
    body = b'{"trigger":"FILE.UPLOADED"}'
    ts = str(time.time() - 3600)  # one hour old
    sig = sign(body, ts, PRIMARY)
    headers = {"BOX-DELIVERY-TIMESTAMP": ts, "BOX-SIGNATURE-PRIMARY": sig}
    assert verify_box_webhook_signature(body, headers, PRIMARY, SECONDARY) is False


def test_missing_signature_rejected():
    body = b'{"trigger":"FILE.UPLOADED"}'
    headers = {"BOX-DELIVERY-TIMESTAMP": str(time.time())}
    assert verify_box_webhook_signature(body, headers, PRIMARY, SECONDARY) is False
