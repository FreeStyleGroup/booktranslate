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

    # Ключ подписи токенов. Значение по умолчанию годится только для
    # разработки: в рабочей среде переменная обязательна, иначе подделать
    # токен сможет любой, кто читал этот файл. Проверка — в validate().
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"

    # Короткий срок жизни доступа и длинный — обновления. Украденный
    # access-токен протухает за четверть часа, а refresh лежит в базе и
    # отзывается: у него есть чему протухнуть принудительно.
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # Где лежат исходные файлы документов. Каталог на диске — временное
    # решение на время разработки и одного сервера; интерфейс хранилища
    # рассчитан на замену объектным (см. app/services/storage.py).
    storage_root: str = "./var/storage"

    # Потолок размера загружаемого файла. Проверяется на лету, по мере
    # чтения: узнавать о превышении после того, как гигабайт уже принят на
    # диск, поздно и дорого.
    max_upload_mb: int = 50

    # Размер сегмента в знаках. Сегмент — это то, что уходит в модель одним
    # куском и что редактор видит одной строкой, поэтому крайности вредны
    # одинаково: слишком короткий лишает перевод контекста и дробит правку,
    # слишком длинный упирается в окно модели и заставляет человека читать
    # абзац целиком ради одной запятой. Целевое значение — ориентир, по
    # которому режутся длинные абзацы; жёсткий предел не превышается никогда,
    # даже если внутри нет ни одной границы предложения.
    segment_target_chars: int = 1200
    segment_hard_limit_chars: int = 3000

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def validate_runtime(self) -> None:
        """Проверки, которые нельзя выразить типом поля.

        Вызывается при сборке приложения: лучше не подняться совсем, чем
        подняться в рабочей среде с ключом подписи из примера.
        """
        if self.environment != "development" and self.jwt_secret == "dev-secret-change-me":
            raise RuntimeError(
                "JWT_SECRET не задан: в среде «" + self.environment + "» "
                "запуск с ключом по умолчанию запрещён"
            )


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс.

    Без кеша каждый запрос заново разбирал бы окружение и .env-файл.
    """
    return Settings()
