import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import TranslationConfig, EmailLog
from app.schemas import ConfigResponse, ConfigUpdate, LogsResponse, EmailLogItem, HealthResponse
from app.services import email_processor

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_config(db: AsyncSession) -> TranslationConfig:
    result = await db.execute(select(TranslationConfig).limit(1))
    config = result.scalar_one_or_none()
    if config is None:
        config = TranslationConfig(
            token=settings.relay_token,
            source_lang="en",
            target_lang="zh",
            dest_email=settings.default_dest_email,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


async def _run_translation(
    log_id: int,
    subject: str,
    from_addr: str,
    body_plain: str | None,
    body_html: str | None,
    dest_email: str,
    source_lang: str,
    target_lang: str,
) -> None:
    try:
        result = email_processor.process_email(
            subject=subject,
            from_addr=from_addr,
            body_plain=body_plain,
            body_html=body_html,
            dest_email=dest_email,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        async with AsyncSessionLocal() as db:
            log = await db.get(EmailLog, log_id)
            if log:
                log.status = result["status"]
                log.input_tokens = result.get("input_tokens")
                log.output_tokens = result.get("output_tokens")
                log.cache_read_tokens = result.get("cache_read_tokens")
                await db.commit()
    except Exception as exc:
        logger.exception("Translation failed for log_id=%d: %s", log_id, exc)
        async with AsyncSessionLocal() as db:
            log = await db.get(EmailLog, log_id)
            if log:
                log.status = "error"
                log.error_message = str(exc)
                await db.commit()


@router.post("/webhook/inbound")
async def inbound_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    form = await request.form()
    sender = str(form.get("sender", ""))
    recipient = str(form.get("recipient", ""))
    subject = str(form.get("subject", ""))
    body_plain = str(form.get("body-plain", "")) or None
    body_html = str(form.get("body-html", "")) or None

    logger.info("Webhook: received email from=%s to=%s", sender, recipient)

    # Ignore emails not addressed to this relay (e.g. obsidian bot emails sharing the route)
    if settings.relay_email and recipient.lower() != settings.relay_email.lower():
        logger.info("Ignoring email to %s (expected %s)", recipient, settings.relay_email)
        return {"status": "ignored"}

    config = await _get_config(db)

    log = EmailLog(
        received_at=datetime.now(timezone.utc),
        from_addr=sender,
        to_addr=recipient,
        subject=subject,
        status="processing",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    background_tasks.add_task(
        _run_translation,
        log_id=log.id,
        subject=subject,
        from_addr=sender,
        body_plain=body_plain,
        body_html=body_html,
        dest_email=config.dest_email,
        source_lang=config.source_lang,
        target_lang=config.target_lang,
    )

    return {"status": "accepted"}


@router.get("/config", response_model=ConfigResponse)
async def get_config(db: AsyncSession = Depends(get_db)) -> ConfigResponse:
    config = await _get_config(db)
    return ConfigResponse(
        relay_email=settings.relay_email,
        source_lang=config.source_lang,
        target_lang=config.target_lang,
        dest_email=config.dest_email,
    )


@router.put("/config", response_model=ConfigResponse)
async def update_config(
    body: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    config = await _get_config(db)

    if body.dest_email is not None:
        config.dest_email = str(body.dest_email)
    if body.source_lang is not None:
        config.source_lang = body.source_lang
    if body.target_lang is not None:
        config.target_lang = body.target_lang

    await db.commit()
    await db.refresh(config)

    return ConfigResponse(
        relay_email=settings.relay_email,
        source_lang=config.source_lang,
        target_lang=config.target_lang,
        dest_email=config.dest_email,
    )


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> LogsResponse:
    count_result = await db.execute(select(func.count(EmailLog.id)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(EmailLog)
        .order_by(EmailLog.received_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()

    return LogsResponse(
        items=[EmailLogItem.model_validate(log) for log in logs],
        total=total,
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
