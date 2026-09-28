"""Kick webhook signature verification (RSA public key)."""

from __future__ import annotations

import base64
import logging
from functools import lru_cache

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

KICK_PUBLIC_KEY_URL = "https://api.kick.com/public/v1/public-key"


@lru_cache(maxsize=1)
def fetch_kick_public_key_pem() -> str:
    """Fetch Kick's webhook verification public key (cached for process lifetime)."""
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(KICK_PUBLIC_KEY_URL)
        resp.raise_for_status()
        data = resp.json()
        # API returns {"data": {"public_key": "-----BEGIN PUBLIC KEY-----\n..."}}
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], dict):
                key = data["data"].get("public_key") or data["data"].get("publicKey")
                if key:
                    return key
            if "public_key" in data:
                return data["public_key"]
        raise ValueError(f"Unexpected public-key response shape: {data!r}")


def clear_public_key_cache() -> None:
    fetch_kick_public_key_pem.cache_clear()


def verify_kick_signature(
    *,
    message_id: str,
    timestamp: str,
    body: bytes,
    signature_b64: str,
    public_key_pem: str | None = None,
) -> bool:
    """
    Verify Kick-Event-Signature.

    Signature is over: f"{message_id}.{timestamp}.{raw_body}" signed with Kick's private key.
    """
    pem = public_key_pem or fetch_kick_public_key_pem()
    public_key = serialization.load_pem_public_key(pem.encode("utf-8"))

    signed_payload = f"{message_id}.{timestamp}.".encode("utf-8") + body
    try:
        signature = base64.b64decode(signature_b64)
    except Exception:
        logger.warning("Invalid base64 signature")
        return False

    try:
        public_key.verify(  # type: ignore[union-attr]
            signature,
            signed_payload,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
    except Exception:
        logger.exception("Signature verification error")
        return False
