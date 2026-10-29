"""Database engine configuration and async session manager."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.common.config import get_settings
from src.db.models import Base

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone scripts and background jobs."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency / generator providing transactional async database session."""
    async with session_scope() as session:
        yield session


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Create all operational database tables if not already present."""
    db_engine = target_engine or engine
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db(target_engine: AsyncEngine | None = None) -> None:
    """Dispose the engine connection pool gracefully."""
    db_engine = target_engine or engine
    await db_engine.dispose()
