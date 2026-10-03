"""Background webhook processor: ack Kick fast, write Snowflake on a worker thread."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ingest.channels import extract_payload_channel_hints, resolve_registered_channel
from ingest.config import Settings, get_settings
from ingest.snowflake_writer import (
    handle_chat_message_sent,
    handle_livestream_status,
    open_snowflake_connection,
    record_webhook_event,
)

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


@dataclass
class WebhookJob:
    event_message_id: str
    event_type: str
    event_version: str | None
    subscription_id: str | None
    payload: dict[str, Any]
    attempts: int = field(default=0)


class WebhookWorker:
    """Single-threaded queue consumer with a long-lived Snowflake connection."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        maxsize: int = 10_000,
        reconnect_backoff_sec: float = 2.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._q: queue.Queue[WebhookJob | None] = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._reconnect_backoff_sec = reconnect_backoff_sec
        self._processed = 0
        self._failed = 0
        self._lock = threading.Lock()

    @property
    def queue_depth(self) -> int:
        return self._q.qsize()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "queue_depth": self._q.qsize(),
                "processed": self._processed,
                "failed": self._failed,
            }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="webhook-snowflake-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Webhook worker started (max queue=%s)", self._q.maxsize)

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("Webhook worker stopped stats=%s", self.stats)

    def enqueue(self, job: WebhookJob) -> None:
        """Raise queue.Full if saturated so the HTTP layer can 503 and Kick retries."""
        self._q.put_nowait(job)

    def _run(self) -> None:
        conn: Any | None = None
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                if conn is None:
                    conn = open_snowflake_connection(self._settings)
                    logger.info("Webhook worker Snowflake connection ready")
                self._process(conn, job)
                with self._lock:
                    self._processed += 1
            except Exception:
                with self._lock:
                    self._failed += 1
                logger.exception(
                    "Webhook worker failed event_id=%s type=%s attempt=%s",
                    job.event_message_id,
                    job.event_type,
                    job.attempts + 1,
                )
                conn = self._close(conn)
                job.attempts += 1
                if job.attempts < _MAX_ATTEMPTS and not self._stop.is_set():
                    time.sleep(self._reconnect_backoff_sec)
                    try:
                        self._q.put_nowait(job)
                    except queue.Full:
                        logger.error(
                            "Dropping event %s — queue full after failure",
                            job.event_message_id,
                        )
                else:
                    logger.error(
                        "Dropping event %s after %s attempts",
                        job.event_message_id,
                        job.attempts,
                    )
            finally:
                self._q.task_done()
        self._close(conn)

    def _close(self, conn: Any | None) -> None:
        if conn is None:
            return None
        try:
            conn.close()
        except Exception:
            logger.exception("Error closing Snowflake connection")
        return None

    def _process(self, conn: Any, job: WebhookJob) -> None:
        settings = self._settings
        hint_slug, hint_bc_id = extract_payload_channel_hints(job.payload)
        channel = resolve_registered_channel(
            conn,
            channel_slug=hint_slug,
            broadcaster_user_id=hint_bc_id,
        )
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
                job.event_message_id,
                hint_slug,
                hint_bc_id,
            )
            is_new = record_webhook_event(
                conn,
                event_message_id=job.event_message_id,
                event_type=job.event_type,
                event_version=job.event_version,
                subscription_id=job.subscription_id,
                processed_ok=True,
                error_message="unregistered_channel",
                channel_slug=resolved_slug,
            )
            conn.commit()
            if not is_new:
                logger.info("Duplicate event %s — skip", job.event_message_id)
            return

        is_new = record_webhook_event(
            conn,
            event_message_id=job.event_message_id,
            event_type=job.event_type,
            event_version=job.event_version,
            subscription_id=job.subscription_id,
            processed_ok=True,
            channel_slug=channel.channel_slug,
        )
        if not is_new:
            logger.info("Duplicate event %s — skip", job.event_message_id)
            conn.commit()
            return

        if job.event_type == "chat.message.sent":
            handle_chat_message_sent(
                conn,
                job.payload,
                event_message_id=job.event_message_id,
                channel_slug=channel.channel_slug,
                source="webhook",
            )
        elif job.event_type == "livestream.status.updated":
            handle_livestream_status(
                conn,
                job.payload,
                channel_slug=channel.channel_slug,
            )
        else:
            logger.info("Ignoring unhandled event type %s", job.event_type)

        conn.commit()


_worker: WebhookWorker | None = None


def get_webhook_worker() -> WebhookWorker:
    global _worker
    if _worker is None:
        _worker = WebhookWorker()
    return _worker
