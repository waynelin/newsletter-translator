"""
Gmail IMAP polling service.

Polls the configured Gmail inbox every IMAP_POLL_INTERVAL seconds for
unseen messages, processes each one through the translation pipeline,
and marks them as seen so they are not re-processed.

Uses imaplib (standard library) wrapped in asyncio.to_thread() to avoid
blocking the event loop during network I/O.
"""

import asyncio
import imaplib
import logging
from datetime import datetime, timezone
from email import message_from_bytes

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import EmailLog, TranslationConfig
from app.services import email_processor
from sqlalchemy import select

logger = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None


def _fetch_and_mark_seen(uid: bytes) -> bytes | None:
    """
    Connect to Gmail IMAP, fetch a single message by UID, mark it as seen,
    and return the raw RFC822 bytes. Runs in a thread via asyncio.to_thread().
    """
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as imap:
        imap.login(settings.imap_user, settings.imap_password)
        imap.select("INBOX")

        # Fetch raw email bytes
        status, data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not data or data[0] is None:
            logger.warning("Could not fetch UID %s: status=%s", uid, status)
            return None

        raw: bytes = data[0][1]  # type: ignore[index]

        # Mark as seen immediately so a crash mid-processing doesn't re-queue it
        imap.uid("store", uid, "+FLAGS", "\\Seen")

        return raw


def _search_unseen() -> list[bytes]:
    """
    Connect to Gmail IMAP, search for UNSEEN messages, and return their UIDs.
    Runs in a thread via asyncio.to_thread().
    """
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as imap:
        imap.login(settings.imap_user, settings.imap_password)
        imap.select("INBOX")

        status, data = imap.uid("search", None, "UNSEEN")
        if status != "OK":
            logger.warning("IMAP SEARCH failed: %s", status)
            return []

        raw_uids = data[0]
        if not raw_uids:
            return []

        return raw_uids.split()


async def _process_message(raw: bytes, config: TranslationConfig) -> None:
    """Parse, log, translate, and forward one raw email."""
    msg = message_from_bytes(raw)
    subject = msg.get("Subject", "")
    from_addr = msg.get("From", "unknown")

    # Create log entry
    async with AsyncSessionLocal() as db:
        log = EmailLog(
            received_at=datetime.now(timezone.utc),
            from_addr=from_addr,
            to_addr=settings.imap_user,
            subject=subject,
            status="processing",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        log_id = log.id

    logger.info("Processing email log_id=%d from=%s subject=%r", log_id, from_addr, subject)

    try:
        result = await asyncio.to_thread(
            email_processor.process_email,
            raw,
            config.dest_email,
            config.source_lang,
            config.target_lang,
        )
        async with AsyncSessionLocal() as db:
            log_row = await db.get(EmailLog, log_id)
            if log_row:
                log_row.status = result["status"]
                log_row.input_tokens = result.get("input_tokens")
                log_row.output_tokens = result.get("output_tokens")
                log_row.cache_read_tokens = result.get("cache_read_tokens")
                await db.commit()
    except Exception as exc:
        logger.exception("Failed to process email log_id=%d: %s", log_id, exc)
        async with AsyncSessionLocal() as db:
            log_row = await db.get(EmailLog, log_id)
            if log_row:
                log_row.status = "error"
                log_row.error_message = str(exc)
                await db.commit()


async def _poll_once() -> None:
    """One polling cycle: search for unseen messages and process each."""
    try:
        uids = await asyncio.to_thread(_search_unseen)
    except Exception as exc:
        logger.error("IMAP search failed: %s", exc)
        return

    if not uids:
        logger.debug("Poll cycle complete — inbox empty")
        return

    logger.info("Poll cycle complete — found %d unseen email(s)", len(uids))

    # Fetch translation config
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TranslationConfig).limit(1))
        config = result.scalar_one_or_none()

    if config is None:
        logger.error("No translation config found — skipping poll cycle")
        return

    for uid in uids:
        try:
            raw = await asyncio.to_thread(_fetch_and_mark_seen, uid)
        except Exception as exc:
            logger.error("Failed to fetch UID %s: %s", uid, exc)
            continue

        if raw:
            await _process_message(raw, config)


async def _polling_loop() -> None:
    """Runs forever, polling on the configured interval."""
    logger.info(
        "IMAP poller started — inbox: %s, interval: %ds",
        settings.imap_user,
        settings.imap_poll_interval,
    )
    while True:
        await _poll_once()
        await asyncio.sleep(settings.imap_poll_interval)


def start_poller() -> asyncio.Task:
    """Schedule the polling loop as a background asyncio task."""
    global _poller_task
    _poller_task = asyncio.create_task(_polling_loop())
    return _poller_task


def stop_poller() -> None:
    global _poller_task
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        _poller_task = None
        logger.info("IMAP poller stopped")


def is_poller_running() -> bool:
    return _poller_task is not None and not _poller_task.done()
