import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text, update

from app.api.routes import router
from app.config import settings
from app.database import engine, init_db, AsyncSessionLocal
from app.models import TranslationConfig, EmailLog

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _migrate_db()
    await _seed_default_config()
    await _mark_stale_processing()
    yield


async def _migrate_db() -> None:
    """Add columns introduced after initial deployment that create_all won't add."""
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(email_logs)"))
        existing_columns = {row[1] for row in result.fetchall()}
        logger.info("_migrate_db: existing columns = %s", existing_columns)

        if "message_id" not in existing_columns:
            logger.info("_migrate_db: adding message_id column")
            await conn.execute(
                text("ALTER TABLE email_logs ADD COLUMN message_id VARCHAR(512)")
            )
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_email_logs_message_id"
                    " ON email_logs (message_id)"
                )
            )
            await conn.commit()
            logger.info("_migrate_db: migration complete")


async def _mark_stale_processing() -> None:
    """Mark any 'processing' rows left over from a previous crashed process as 'error'."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(EmailLog)
            .where(EmailLog.status == "processing")
            .values(status="error", error_message="Interrupted by server restart")
        )
        await db.commit()


async def _seed_default_config() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TranslationConfig).limit(1))
        if result.scalar_one_or_none() is None:
            db.add(TranslationConfig(
                token=settings.relay_token,
                source_lang="en",
                target_lang="zh-tw",
                dest_email=settings.default_dest_email,
            ))
            await db.commit()


app = FastAPI(title="Newsletter Translator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router, prefix="/api")


@app.get("/")
async def serve_index() -> FileResponse:
    return FileResponse("app/static/index.html")
