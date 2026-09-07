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

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_session
from app.main import create_app
from app.models.organization import User, UserStatus
from app.services.providers import (
    Explanation,
    LookupRequest,
    Reference,
    StubProvider,
    TermLookupProvider,
    Translated,
    TranslationProvider,
    TranslationRequest,
    Usage,
    get_lookup,
    get_provider,
)
from app.services.storage import LocalStorage, ObjectStorage, get_storage

DATABASE_URL = os.getenv("DATABASE_URL")

# Администратор площадки для тестов. Заводится прямо в базе — ровно так же,
# как в жизни его заводит консольная команда: первого администратора
# неоткуда одобрить, иначе площадка не открылась бы никогда.
# Домен именно example.com: зона .test зарезервирована, и проверка адреса
# отвергает её раньше, чем дело доходит до самого теста.
ROOT_EMAIL = "root@example.com"
ROOT_PASSWORD = "root-password-for-tests"

# Ограничитель частоты в тестах поднят до недостижимого: тест на вход и
# одобрение — это несколько запросов подряд с одного адреса, и обычная мера
# завалила бы половину набора отказом «слишком часто». Сам ограничитель
# проверяется отдельно, на приложении со своими настройками
# (tests/test_throttle.py).
get_settings().rate_limit_per_minute = 100_000
get_settings().auth_rate_limit_per_minute = 100_000

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


class RecordingProvider(StubProvider):
    """Заглушка, запоминающая запросы.

    Переводит ровно так же, как обычная, но сохраняет то, что ей пришло:
    иначе про контекст и термины, уехавшие в модель, тест может судить
    только по итоговому тексту — а там их не видно.
    """

    def __init__(self, log: list[TranslationRequest]) -> None:
        self._log = log

    async def translate(self, requests: list[TranslationRequest]) -> Translated:
        self._log.extend(requests)

        return await super().translate(requests)


@pytest.fixture
def provider_log() -> list[TranslationRequest]:
    """Запросы, ушедшие провайдеру за время теста."""
    return []


class ScriptedLookup:
    """Внешний источник справок, отвечающий по сценарию теста.

    В сеть не ходит и ходить не должен: проверяется каталог — то, что
    справка спрашивается один раз и переживает документ, — а не умение
    модели искать.
    """

    def __init__(self, log: list[LookupRequest], answers: dict[str, Explanation]) -> None:
        self._log = log
        self._answers = answers

    @property
    def name(self) -> str:
        return "test-lookup"

    async def lookup(self, request: LookupRequest) -> Explanation:
        self._log.append(request)

        return self._answers.get(request.source_term.casefold()) or Explanation(
            found=True,
            suggested_target=f"перевод:{request.source_term}",
            definition=f"Справка про {request.source_term}",
            references=(Reference(title="Отраслевой справочник", url="https://example.org/term"),),
            usage=Usage(input_tokens=1000, output_tokens=200),
            searches=1,
        )


@pytest.fixture
def lookup_log() -> list[LookupRequest]:
    """Термины, ушедшие во внешний источник за время теста."""
    return []


@pytest.fixture
def lookup_answers() -> dict[str, Explanation]:
    """Заготовленные ответы источника по терминам (ключ — в нижнем регистре)."""
    return {}


@pytest.fixture
async def root(session: AsyncSession) -> User:
    """Администратор площадки.

    Нужен почти каждому тесту: регистрация теперь только заявка, и доступ
    новому пользователю открывает он. Заводится записью в базу, потому что
    первого администратора одобрить некому.
    """
    user = User(
        email=ROOT_EMAIL,
        full_name="Администратор площадки",
        password_hash=hash_password(ROOT_PASSWORD),
        status=UserStatus.ACTIVE,
        is_superuser=True,
    )

    session.add(user)
    await session.commit()

    return user


@pytest.fixture
async def db_client(
    session: AsyncSession,
    root: User,
    storage_root: Path,
    provider_log: list[TranslationRequest],
    lookup_log: list[LookupRequest],
    lookup_answers: dict[str, Explanation],
) -> AsyncGenerator[AsyncClient]:
    """Клиент к приложению, работающему в транзакции теста.

    Отдельная фикстура, а не общая с `client`: тест, которому база не
    нужна, не должен падать из-за её отсутствия.
    """
    app = create_app()

    async def override_session() -> AsyncGenerator[AsyncSession]:
        yield session

    def override_storage() -> ObjectStorage:
        return LocalStorage(storage_root)

    def override_provider() -> TranslationProvider:
        return RecordingProvider(provider_log)

    def override_lookup() -> TermLookupProvider:
        return ScriptedLookup(lookup_log, lookup_answers)

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage] = override_storage
    app.dependency_overrides[get_provider] = override_provider
    app.dependency_overrides[get_lookup] = override_lookup

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client

    app.dependency_overrides.clear()
