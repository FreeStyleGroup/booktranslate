"""Настройки рабочего пространства, влияющие на перевод.

Отдельно от уведомлений: те — про то, кому сообщать, эти — про то, чем
переводить. Один набор на пространство, и это ограничение стоит в базе.

Модель хранится именем, а не ссылкой на каталог: каталог живёт в коде и
меняется с выкатом, а выбранное пространством должно пережить смену
каталога и быть видно в базе как есть. Пусто — умолчание площадки.

Тематика и разрешение на общий словарь — тоже здесь: обе вещи про
пространство целиком. Тематика открывает подсказки из общего словаря
площадки по своей области; разрешение отдаёт термины загруженных словарей
площадке. Выключено, пока не включили: чужой словарь по умолчанию чужой.
"""

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKey
from app.models.qa import QAScope


class MemoryPublish(str, enum.Enum):
    VERIFIED = "verified"
    CLOSED = "closed"


class WorkspaceSettings(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "workspace_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    translation_model: Mapped[str | None] = mapped_column(String(120))

    # Тематика пространства из списка в коде (`app.services.subjects`).
    # Пусто — подсказок из общего словаря нет: без тематики они были бы
    # из чужой области.
    subject: Mapped[str | None] = mapped_column(String(60))

    # Разрешение отдавать термины загруженных словарей в общий словарь
    # площадки. Термины, не текст книг: память переводов не делится никогда.
    share_glossary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Критичное замечание решает не тот, кто его нашёл или исправил. Выключено по умолчанию: в
    # команде из одного редактора это правило остановило бы работу.
    two_person_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Держат ли выпуск незакрытые незначительные замечания. Критичные и серьёзные держат всегда.
    minor_blocks_release: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Что отдавать на смысловую сверку: второй проход модели по всей книге удваивает расход.
    semantic_scope: Mapped[QAScope] = mapped_column(
        Enum(QAScope, name="qa_scope", native_enum=True), nullable=False, default=QAScope.RISKY
    )

    # Когда исправление попадает в память переводов: после проверки или только после закрытия.
    memory_publish_on: Mapped[MemoryPublish] = mapped_column(
        Enum(MemoryPublish, name="memory_publish", native_enum=True),
        nullable=False,
        default=MemoryPublish.VERIFIED,
    )
