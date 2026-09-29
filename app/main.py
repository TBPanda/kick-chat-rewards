"""FastAPI Kick webhook receiver (multi-channel)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ingest.channels import extract_payload_channel_hints, resolve_registered_channel
from ingest.config import get_settings
from ingest.signature import verify_kick_signature
from ingest.snowflake_writer import (
    handle_chat_message_sent,
    handle_livestream_status,
    record_webhook_event,
    snowflake_connection,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("kick_webhook")

app = FastAPI(
    title="Kick Chat Activity Ingest",
    description="Receives Kick webhooks for registered channels (multi-channel CORE)",
    version="0.2.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/kick")
async def kick_webhook(
    request: Request,
    kick_event_message_id: str | None = Header(default=None, alias="Kick-Event-Message-Id"),
    kick_event_message_timestamp: str | None = Header(
        default=None, alias="Kick-Event-Message-Timestamp"
    ),
    kick_event_signature: str | None = Header(default=None, alias="Kick-Event-Signature"),
    kick_event_type: str | None = Header(default=None, alias="Kick-Event-Type"),
    kick_event_version: str | None = Header(default=None, alias="Kick-Event-Version"),
    kick_event_subscription_id: str | None = Header(
        default=None, alias="Kick-Event-Subscription-Id"
    ),
) -> Response:
    settings = get_settings()
    body = await request.body()

    if not kick_event_message_id or not kick_event_type:
        raise HTTPException(status_code=400, detail="Missing Kick event headers")

    if not settings.kick_webhook_skip_verify:
        if not kick_event_signature or not kick_event_message_timestamp:
            raise HTTPException(status_code=401, detail="Missing signature headers")
        ok = verify_kick_signature(
            message_id=kick_event_message_id,
            timestamp=kick_event_message_timestamp,
            body=body,
            signature_b64=kick_event_signature,
        )
        if not ok:
            logger.warning("Signature verification failed for %s", kick_event_message_id)
            raise HTTPException(status_code=401, detail="Invalid signature")
    else:
        logger.warning("KICK_WEBHOOK_SKIP_VERIFY enabled — not verifying signatures")

    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    hint_slug, hint_bc_id = extract_payload_channel_hints(payload)

    try:
        with snowflake_connection(settings) as conn:
            channel = resolve_registered_channel(
                conn,
                channel_slug=hint_slug,
                broadcaster_user_id=hint_bc_id,
            )
            # Fallback for early payloads missing broadcaster: env bootstrap channel
            if channel is None and not hint_slug and not hint_bc_id:
                channel = resolve_registered_channel(
                    conn,
                    channel_slug=settings.kick_channel_slug,
                    broadcaster_user_id=settings.kick_broadcaster_user_id,
                )

            resolved_slug = channel.channel_slug if channel else hint_slug

            if channel is None:
                logger.warning(
                    "Ignoring event %s for unregistered channel slug=%s broadcaster_id=%s",
                    kick_event_message_id,
                    hint_slug,
                    hint_bc_id,
                )
                is_new = record_webhook_event(
                    conn,
                    event_message_id=kick_event_message_id,
                    event_type=kick_event_type,
                    event_version=kick_event_version,
                    subscription_id=kick_event_subscription_id,
                    processed_ok=True,
                    error_message="unregistered_channel",
                    channel_slug=resolved_slug,
                )
                conn.commit()
                if not is_new:
                    return JSONResponse({"status": "duplicate"}, status_code=200)
                return JSONResponse({"status": "ignored_unregistered_channel"}, status_code=200)

            is_new = record_webhook_event(
                conn,
                event_message_id=kick_event_message_id,
                event_type=kick_event_type,
                event_version=kick_event_version,
                subscription_id=kick_event_subscription_id,
                processed_ok=True,
                channel_slug=channel.channel_slug,
            )
            if not is_new:
                logger.info("Duplicate event %s — acknowledging", kick_event_message_id)
                conn.commit()
                return JSONResponse({"status": "duplicate"}, status_code=200)

            if kick_event_type == "chat.message.sent":
                handle_chat_message_sent(
                    conn,
                    payload,
                    event_message_id=kick_event_message_id,
                    channel_slug=channel.channel_slug,
                    source="webhook",
                )
            elif kick_event_type == "livestream.status.updated":
                handle_livestream_status(
                    conn,
                    payload,
                    channel_slug=channel.channel_slug,
                )
            else:
                logger.info("Ignoring unhandled event type %s", kick_event_type)

            conn.commit()
    except Exception:
        logger.exception("Failed processing webhook %s", kick_event_message_id)
        raise HTTPException(status_code=500, detail="Processing failed")

    return JSONResponse({"status": "ok"}, status_code=200)
