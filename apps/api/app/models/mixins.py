"""Общие части доменных моделей.

Здесь же реализована мультитенантность: `TenantMixin` добавляет сущности
организацию-владельца. Решение из `docs/DECISIONS.md` — тенант закладывается
с первого дня, потому что привинтить его к готовой схеме дороже, чем нести
лишнюю колонку в первые месяцы.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKey:
    """Идентификатор — UUID, а не автоинкремент.

    Идентификаторы уезжают в адреса и во внешние системы, а последовательный
    номер выдаёт объём базы и позволяет перебирать чужие записи. Значение
    генерируется на стороне приложения: объект получает id до вставки, и его
    можно связывать с другими до похода в базу.
    """

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """Принадлежность записи организации.

    Колонка обязательная и с внешним ключом: запись без владельца — это
    запись, которую увидит не тот клиент. Удаление организации уносит её
    данные каскадом, иначе после ухода клиента в базе остаются осиротевшие
    строки с его текстами.
    """

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
