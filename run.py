"""
Local development entry point.

Usage:
    python run.py
"""

import asyncio
import logging

import uvicorn
from sqlalchemy import select

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.models import TranslationConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def seed_default_config() -> None:
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
    await init_db()
    await seed_default_config()

    logger.info("Web UI available at http://localhost:%d", settings.app_port)
    logger.info("Mailgun webhook endpoint: POST /api/webhook/inbound")
    logger.info("Relay email: %s", settings.relay_email)

    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
