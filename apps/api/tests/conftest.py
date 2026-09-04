"""Общая обвязка тестов.

Каждый тест работает в транзакции, которая в конце откатывается: база
остаётся в том же состоянии, тесты не зависят от порядка запуска и не
требуют чистки между собой.

Без адреса базы тесты, которым она нужна, пропускаются — на машине
разработчика Postgres может быть не поднят, и это не повод считать сборку
сломанной. В CI адрес задан, и они выполняются по-настоящему.
"""

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_session
from app.main import create_app
from app.services.storage import LocalStorage, ObjectStorage, get_storage

DATABASE_URL = os.getenv("DATABASE_URL")

requires_database = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="нужен Postgres: задайте DATABASE_URL (в CI он задан)",
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(DATABASE_URL or "", poolclass=None)

    connection = await engine.connect()
    transaction = await connection.begin()

    # join_transaction_mode="create_savepoint": сервисы внутри вызывают
    # commit, и без вложенной точки сохранения он завершил бы внешнюю
    # транзакцию — откатывать после теста было бы нечего.
    maker = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    async with maker() as db_session:
        yield db_session

    await transaction.rollback()
    await connection.close()
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Клиент без базы.

    Годится для проверок, которые до базы не доходят: отказ без токена,
    разбор испорченного токена, health. Соединение при этом не
    открывается — сессия SQLAlchemy подключается лениво, на первом запросе
    к базе.
    """
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as async_client:
        yield async_client


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    """Каталог хранилища на время одного теста.

    Свой у каждого теста: загруженные файлы не переживают его и не
    попадают в рабочий каталог разработчика.
    """
    return tmp_path / "storage"


@pytest.fixture
async def db_client(session: AsyncSession, storage_root: Path) -> AsyncGenerator[AsyncClient]:
    """Клиент к приложению, работающему в транзакции теста.

    Отдельная фикстура, а не общая с `client`: тест, которому база не
    нужна, не должен падать из-за её отсутствия.
    """
    app = create_app()

    async def override_session() -> AsyncGenerator[AsyncSession]:
        yield session

    def override_storage() -> ObjectStorage:
        return LocalStorage(storage_root)

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage] = override_storage

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client

    app.dependency_overrides.clear()
