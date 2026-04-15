from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import TranslationConfig, EmailLog
from app.schemas import ConfigResponse, ConfigUpdate, LogsResponse, EmailLogItem, HealthResponse

router = APIRouter()


async def _get_config(db: AsyncSession) -> TranslationConfig:
    result = await db.execute(select(TranslationConfig).limit(1))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=500, detail="No translation config found")
    return config


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
    from app.services.imap_poller import is_poller_running
    return HealthResponse(status="ok", poller_running=is_poller_running())
