"""
Entry point: starts both the FastAPI web server and the aiosmtpd SMTP server.

Usage:
    python run.py

Both servers run in the same process. The SMTP controller runs on its own thread
(aiosmtpd Controller pattern); uvicorn runs on asyncio.
"""

import asyncio
import logging

import uvicorn
from sqlalchemy import select

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.models import TranslationConfig
from app.smtp.handler import start_smtp_controller, stop_smtp_controller

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
                token=settings.relay_token,
                source_lang="en",
                target_lang="zh",
                dest_email=settings.default_dest_email,
            )
            db.add(config)
            await db.commit()
            logger.info(
                "Seeded default config: relay=%s dest=%s",
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

    # 3. Start SMTP controller (runs on its own thread)
    smtp_controller = start_smtp_controller()

    logger.info("Web UI available at http://localhost:%d", settings.app_port)
    logger.info("Relay email: %s (SMTP port %d)", settings.relay_email, settings.smtp_port)

    # 4. Start uvicorn (runs on asyncio event loop until interrupted)
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
        stop_smtp_controller()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
