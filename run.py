"""
Entry point: starts the FastAPI web server and the Gmail IMAP polling loop.

Usage:
    python run.py

The IMAP poller runs as a background asyncio task alongside uvicorn.
"""

import asyncio
import logging

import uvicorn
from sqlalchemy import select

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.models import TranslationConfig
from app.services.imap_poller import start_poller, stop_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def seed_default_config() -> None:
    """Insert the default TranslationConfig row if none exists."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TranslationConfig).limit(1))
        if result.scalar_one_or_none() is None:
            config = TranslationConfig(
                token="default",
                source_lang="en",
                target_lang="zh",
                dest_email=settings.default_dest_email,
            )
            db.add(config)
            await db.commit()
            logger.info(
                "Seeded default config: inbox=%s dest=%s",
                settings.relay_email,
                settings.default_dest_email,
            )
        else:
            logger.info("Translation config already exists, skipping seed")


async def main() -> None:
    # 1. Initialize database (create tables)
    await init_db()

    # 2. Seed default config row
    await seed_default_config()

    # 3. Start IMAP polling loop as a background asyncio task
    start_poller()

    logger.info("Web UI available at http://localhost:%d", settings.app_port)
    logger.info(
        "Polling inbox: %s every %ds",
        settings.imap_user,
        settings.imap_poll_interval,
    )

    # 4. Start uvicorn (runs until interrupted)
    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        stop_poller()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
