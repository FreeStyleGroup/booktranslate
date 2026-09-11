"""Проверки настроек, которые нельзя выразить типом поля.

Без базы и без приложения: `Settings.validate_runtime` — чистая функция
над значениями, и падать она должна ещё до того, как что-то поднялось.
"""

import pytest

from app.core.config import Settings

_STRONG_SECRET = "a" * 64
_PRODUCTION = {
    "environment": "production",
    "cors_origins": ["https://app.example.ru"],
    "allowed_hosts": ["api.example.ru"],
}


def test_production_refuses_default_secret() -> None:
    settings = Settings(**_PRODUCTION, jwt_secret="dev-secret-change-me")

    with pytest.raises(RuntimeError, match="JWT_SECRET не задан"):
        settings.validate_runtime()


def test_production_refuses_short_secret() -> None:
    """Короткий ключ HS256 подбирается офлайн по любому выданному токену.

    Ошибка в конфигурации, а не в коде, и лучше не подняться совсем, чем
    подписывать токены ключом из восьми знаков.
    """
    settings = Settings(**_PRODUCTION, jwt_secret="short-key")

    with pytest.raises(RuntimeError, match="короче 32 байт"):
        settings.validate_runtime()


def test_production_accepts_generated_secret() -> None:
    settings = Settings(**_PRODUCTION, jwt_secret=_STRONG_SECRET)

    settings.validate_runtime()


def test_development_does_not_check_secret() -> None:
    settings = Settings(environment="development", jwt_secret="x")

    settings.validate_runtime()
