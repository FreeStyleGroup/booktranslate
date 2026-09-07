"""Точка входа API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import handle_domain_error
from app.api.routes import auth, documents, health, projects, segments
from app.core.config import get_settings
from app.services.errors import DomainError


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

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API платформы перевода технической документации",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Один обработчик на всё дерево доменных ошибок: Starlette ищет
    # обработчик по предкам исключения, поэтому наследники находятся сами.
    app.add_exception_handler(DomainError, handle_domain_error)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(documents.router)
    app.include_router(segments.router)

    return app


app = create_app()
