"""
aiosmtpd handler for receiving inbound newsletters.

handle_DATA returns '250 OK' immediately to the sender, then processes
the email asynchronously so we don't block the SMTP session during
the potentially slow translation API call.
"""

import asyncio
import logging
from datetime import datetime, timezone

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import Envelope, Session, SMTP

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import EmailLog, TranslationConfig
from app.services import email_processor

logger = logging.getLogger(__name__)

# Module-level reference so the health endpoint can check status
_controller: Controller | None = None


class TranslationHandler:
    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:
        mail_from = envelope.mail_from or "unknown"
        rcpt_to = envelope.rcpt_tos[0] if envelope.rcpt_tos else ""
        raw_content: bytes = envelope.content  # type: ignore[assignment]

        logger.info("SMTP: received email from=%s to=%s", mail_from, rcpt_to)

        # Persist an initial log entry, then dispatch processing as a background task
        asyncio.ensure_future(
            _process_and_log(raw_content, mail_from, rcpt_to)
        )

        return "250 Message accepted for translation"


async def _process_and_log(raw_content: bytes, mail_from: str, rcpt_to: str) -> None:
    """Look up config, translate, forward, and log the result."""
    async with AsyncSessionLocal() as db:
        # Fetch the single translation config (MVP: one global config)
        from sqlalchemy import select
        result = await db.execute(select(TranslationConfig).limit(1))
        config = result.scalar_one_or_none()

        if config is None:
            logger.error("No translation config found — dropping email from %s", mail_from)
            return

        # Extract subject for logging (best-effort, before full parse)
        import email as _email_mod
        msg = _email_mod.message_from_bytes(raw_content)
        subject = msg.get("Subject", "")

        # Create log entry
        log = EmailLog(
            received_at=datetime.now(timezone.utc),
            from_addr=mail_from,
            to_addr=rcpt_to,
            subject=subject,
            status="processing",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        log_id = log.id

    # Run translation outside the DB session to avoid holding it open during API call
    try:
        result = email_processor.process_email(
            raw_content=raw_content,
            dest_email=config.dest_email,
            source_lang=config.source_lang,
            target_lang=config.target_lang,
        )
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select as sel
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


def start_smtp_controller() -> Controller:
    """Start the aiosmtpd controller and return it."""
    global _controller
    handler = TranslationHandler()
    _controller = Controller(
        handler,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
    )
    _controller.start()
    logger.info("SMTP server listening on %s:%d", settings.smtp_host, settings.smtp_port)
    return _controller


def stop_smtp_controller() -> None:
    global _controller
    if _controller is not None:
        _controller.stop()
        _controller = None
        logger.info("SMTP server stopped")


def is_smtp_running() -> bool:
    return _controller is not None
