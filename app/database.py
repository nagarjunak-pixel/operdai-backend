"""Async SQLAlchemy engine, session factory, and base model."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Async engine for the main (superuser) connection
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a DB session (no tenant context)."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_tenant_db(
    agency_id: str,
    role: str,
    client_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a DB session with RLS tenant context set.
    Must be called with the current user's agency_id and role.
    """
    async with async_session_factory() as session:
        try:
            # Set RLS session variables
            await session.execute(
                text(f"SET app.current_agency_id = '{agency_id}'")
            )
            await session.execute(
                text(f"SET app.current_role = '{role}'")
            )
            if client_id:
                await session.execute(
                    text(f"SET app.current_client_id = '{client_id}'")
                )
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def tenant_session(
    agency_id: str,
    role: str,
    client_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Context manager version of get_tenant_db for use outside FastAPI DI."""
    async with async_session_factory() as session:
        try:
            await session.execute(
                text(f"SET app.current_agency_id = '{agency_id}'")
            )
            await session.execute(
                text(f"SET app.current_role = '{role}'")
            )
            if client_id:
                await session.execute(
                    text(f"SET app.current_client_id = '{client_id}'")
                )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
