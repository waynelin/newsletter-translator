from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create all tables then apply any missing column migrations."""
    async with engine.begin() as conn:
        from app import models  # noqa: F401 — registers models with Base
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


async def _migrate(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(email_logs)"))
    existing = {row[1] for row in result.fetchall()}
    if "message_id" not in existing:
        await conn.execute(text("ALTER TABLE email_logs ADD COLUMN message_id VARCHAR(512)"))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_email_logs_message_id ON email_logs (message_id)"
        ))


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        yield session
