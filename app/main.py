"""FastAPI Kick webhook receiver (multi-channel)."""

from __future__ import annotations

import json
import logging
import queue
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ingest.config import get_settings
from ingest.signature import verify_kick_signature
from ingest.subscription_watchdog import get_subscription_watchdog
from ingest.webhook_worker import WebhookJob, get_webhook_worker

# Railway treats stderr as severity=error; keep INFO on stdout.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("kick_webhook")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    worker = get_webhook_worker()
    worker.start()
    watchdog = get_subscription_watchdog()
    if settings.subscription_watchdog_enabled:
        watchdog.start()
    else:
        logger.warning("Subscription watchdog disabled via config")
    try:
        yield
    finally:
        watchdog.stop()
        worker.stop()


app = FastAPI(
    title="Kick Chat Activity Ingest",
    description="Receives Kick webhooks for registered channels (multi-channel CORE)",
    version="0.3.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    worker = get_webhook_worker()
    watchdog = get_subscription_watchdog()
    return {
        "status": "ok",
        "worker": worker.stats,
        "watchdog": watchdog.status,
    }


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

    job = WebhookJob(
        event_message_id=kick_event_message_id,
        event_type=kick_event_type,
        event_version=kick_event_version,
        subscription_id=kick_event_subscription_id,
        payload=payload,
    )
    try:
        get_webhook_worker().enqueue(job)
    except queue.Full as exc:
        logger.error("Webhook queue full — rejecting %s", kick_event_message_id)
        raise HTTPException(status_code=503, detail="Ingest queue full") from exc

    # Ack immediately so Kick does not time out / drop the subscription.
    return JSONResponse({"status": "accepted"}, status_code=200)
