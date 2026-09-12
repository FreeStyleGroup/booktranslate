"""Точка входа API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import handle_domain_error
from app.api.routes import (
    admin,
    admin_glossary,
    auth,
    catalog,
    documents,
    health,
    jobs,
    overview,
    preferences,
    projects,
    segments,
    team,
    terminology,
    translation,
    usage,
)
from app.api.throttle import RateLimitMiddleware
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.errors import DomainError
from app.services.translation import recover_interrupted

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Что делается при старте процесса.

    Документы, оставшиеся в «разбирается» и «переводится» от убитого
    процесса, возвращаются в состояние по данным: отметку ставил он, и
    снять её больше некому. Без этого каждый запуск перевода после
    перезапуска контейнера отвечал бы «документ уже переводится».

    База, недоступная в момент старта, процесс не роняет: сессия
    подключается лениво, и остальное приложение поднимется как прежде.
    Подвисшие документы при этом дождутся первого вызова с force=true —
    порог давности их всё равно выпустит.
    """
    try:
        async with get_sessionmaker()() as session:
            recovered = await recover_interrupted(session)
    except (SQLAlchemyError, OSError):
        logger.exception("Не удалось проверить подвисшие документы при старте")
    else:
        if recovered:
            logger.warning("Возвращено из подвисшего состояния документов: %d", len(recovered))

    yield


def create_app() -> FastAPI:
    """Приложение собирается функцией, а не на уровне модуля.

    Тестам нужен экземпляр со своими настройками, а импорт модуля отдаёт
    один и тот же объект на весь процесс.
    """
    settings = get_settings()
    # Проверки, которые нельзя выразить типом поля, — например запрет
    # ключа подписи из примера вне разработки. Лучше не подняться совсем,
    # чем подняться в рабочей среде с известным всем секретом.
    settings.validate_runtime()

    development = settings.environment == "development"

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API платформы перевода технической документации",
        # Схема открывает весь список ручек, включая управление доступом.
        # Разработке она нужна каждый день, снаружи — только тому, кто ищет,
        # за что взяться.
        docs_url="/docs" if development else None,
        redoc_url="/redoc" if development else None,
        openapi_url="/openapi.json" if development else None,
        lifespan=lifespan,
    )

    # Порядок обёрток обратный порядку добавления: ограничитель частоты
    # добавлен первым и потому отрабатывает последним — уже после проверки
    # имени узла и заголовков источника, на которые запрос тратить нечего.
    app.add_middleware(
        RateLimitMiddleware,
        general=settings.rate_limit_per_minute,
        guarded=settings.auth_rate_limit_per_minute,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Иначе витрина не прочитает служебные заголовки ответа при
        # обращении с другого домена — а она живёт именно на другом.
        expose_headers=["X-Untranslated-Blocks"],
    )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    # Один обработчик на всё дерево доменных ошибок: Starlette ищет
    # обработчик по предкам исключения, поэтому наследники находятся сами.
    app.add_exception_handler(DomainError, handle_domain_error)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(admin_glossary.router)
    app.include_router(overview.router)
    app.include_router(projects.router)
    app.include_router(documents.router)
    app.include_router(segments.router)
    app.include_router(terminology.router)
    app.include_router(catalog.router)
    app.include_router(translation.router)
    app.include_router(jobs.router)
    app.include_router(preferences.router)
    app.include_router(usage.router)
    app.include_router(team.router)

    return app


app = create_app()
