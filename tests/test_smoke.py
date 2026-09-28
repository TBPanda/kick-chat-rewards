"""Lightweight unit tests (no Snowflake / Kick credentials required)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.signature import verify_kick_signature  # noqa: E402
from ingest.snowflake_writer import is_command_message  # noqa: E402
from import_cli.import_messages import _normalize_row  # noqa: E402


def test_is_command_message() -> None:
    assert is_command_message("!song")
    assert is_command_message("  !clip me")
    assert not is_command_message("hello !song")
    assert not is_command_message("GG")
    assert not is_command_message(None)


def test_normalize_flat_and_kick_shaped() -> None:
    flat = _normalize_row(
        {
            "message_id": "m1",
            "kick_user_id": "42",
            "username": "alice",
            "content": "hi",
            "created_at": "2025-01-01T00:00:00Z",
        },
        "amirphanthom",
    )
    assert flat is not None
    assert flat["kick_user_id"] == 42
    assert flat["channel_slug"] == "amirphanthom"

    kick = _normalize_row(
        {
            "message_id": "m2",
            "content": "yo",
            "created_at": "2025-01-01T00:00:00Z",
            "sender": {"user_id": 7, "username": "bob"},
            "broadcaster": {"channel_slug": "amirphanthom"},
        },
        "amirphanthom",
    )
    assert kick is not None
    assert kick["username"] == "bob"


def test_signature_roundtrip() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    message_id = "01HZTEST"
    timestamp = "2025-01-14T16:08:06Z"
    body = b'{"message_id":"x"}'
    signed = f"{message_id}.{timestamp}.".encode("utf-8") + body
    sig = private_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig).decode("ascii")

    assert verify_kick_signature(
        message_id=message_id,
        timestamp=timestamp,
        body=body,
        signature_b64=sig_b64,
        public_key_pem=public_pem,
    )
    assert not verify_kick_signature(
        message_id=message_id,
        timestamp=timestamp,
        body=b"tampered",
        signature_b64=sig_b64,
        public_key_pem=public_pem,
    )


if __name__ == "__main__":
    test_is_command_message()
    test_normalize_flat_and_kick_shaped()
    test_signature_roundtrip()
    print("All tests passed.")
