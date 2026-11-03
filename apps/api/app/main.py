"""Точка входа API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import handle_domain_error
from app.api.routes import (
    admin,
    admin_glossary,
    auth,
    books,
    catalog,
    chapter_translation,
    chapters,
    documents,
    glossary,
    glossary_versions,
    health,
    issues,
    jobs,
    masters,
    memory,
    objects,
    overview,
    preferences,
    projects,
    qa,
    reviews,
    search,
    team,
    terminology,
    usage,
)
from app.api.throttle import RateLimitMiddleware
from app.core.config import get_settings
from app.services.errors import DomainError

logger = logging.getLogger(__name__)


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
    app.include_router(books.router)
    app.include_router(issues.router)
    app.include_router(qa.router)
    app.include_router(reviews.router)
    app.include_router(chapters.router)
    app.include_router(masters.router)
    app.include_router(objects.router)
    app.include_router(documents.router)
    app.include_router(terminology.router)
    app.include_router(glossary_versions.router)
    app.include_router(chapter_translation.router)
    app.include_router(catalog.router)
    app.include_router(glossary.router)
    app.include_router(jobs.router)
    app.include_router(memory.router)
    app.include_router(search.router)
    app.include_router(preferences.router)
    app.include_router(usage.router)
    app.include_router(team.router)

    return app


app = create_app()
