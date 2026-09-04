"""Подключение к базе и выдача сессий.

Движок создаётся один на процесс: пул соединений имеет смысл только тогда,
когда его переиспользуют.
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        # Соединение, пролежавшее без дела полчаса, часто уже закрыто с той
        # стороны — балансировщиком или самим Postgres. pre_ping проверяет
        # его перед выдачей и меняет редкую загадочную ошибку на лишний
        # дешёвый запрос.
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Зависимость FastAPI: сессия на запрос.

    Коммит остаётся за вызывающим кодом — сервис сам решает, где границы
    транзакции; здесь только гарантия, что сессия закроется.
    """
    async with get_sessionmaker()() as session:
        yield session
