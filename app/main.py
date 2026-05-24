from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api.routes import router
from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.models import TranslationConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_default_config()
    yield


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
