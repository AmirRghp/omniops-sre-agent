"""FastAPI application entrypoint for the OmniOps SRE Agent."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import router
from src.common.config import get_settings
from src.common.logger import setup_logger
from src.db.session import close_db, init_db

logger = setup_logger("api_main")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ensure operational tables exist before serving and release the pool after."""
    await init_db()
    logger.info("OmniOps API ready")
    yield
    await close_db()


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)
app.include_router(router, prefix="/api/v1")
