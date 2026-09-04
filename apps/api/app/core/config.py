"""Настройки приложения.

Всё, что зависит от среды, читается из переменных окружения: приложение
одинаково запускается в контейнере, на сервере и в тестах, а секреты не
лежат в коде.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BookTranslate API"
    environment: str = "development"
    debug: bool = False

    # Адрес базы. Драйвер asyncpg указан прямо в схеме: SQLAlchemy выбирает
    # синхронный или асинхронный движок именно по ней, и без "+asyncpg"
    # приложение падает не при старте, а на первом запросе.
    database_url: str = (
        "postgresql+asyncpg://booktranslate:booktranslate@localhost:5432/booktranslate"
    )

    # Домены витрины, которым разрешён доступ к API из браузера.
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс.

    Без кеша каждый запрос заново разбирал бы окружение и .env-файл.
    """
    return Settings()
