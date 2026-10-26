"""Журнал решений: кто, когда и на каком основании что решил.

Процесс перевода построен на утверждениях — границы главы, версия
глоссария, подтверждение ошибки, выпуск. Каждое из них нужно уметь
предъявить через полгода: без записи «утвердил такой-то тогда-то» выпуск
невозможно считать воспроизводимым, а именно этого требует ТЗ.

Точечные отметки колонками в проекте уже есть (`users.status_changed_by_id`,
`glossary_uploads.reviewed_by_id`, `invitations.accepted_by_id`), но они
отвечают только на вопрос «кто последний». Здесь хранится последовательность
решений целиком, и прежняя запись не затирается следующей.

🔥 `actor_id` пустой означает, что решение принял сервис. Это не изъян
данных, а сознательная возможность: автоматический режим проходит те же
гейты, что человек, и обязан оставлять такой же след. Если бы автор был
обязателен, автоматические решения пришлось бы либо приписывать живому
человеку, либо не записывать вовсе — и то и другое хуже.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, UUIDPrimaryKey


class AuditEvent(UUIDPrimaryKey, TenantMixin, Base):
    """Одно принятое решение.

    `TimestampMixin` здесь не используется: у события нет «момента
    последнего изменения», оно не изменяется вовсе. Колонка `updated_at`
    у записи, которую запрещено править, только вводила бы в заблуждение.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # Лента организации: «что происходило за последние дни».
        Index("audit_events_organization_time", "organization_id", "created_at"),
        # История одного объекта: «что решали по этой главе».
        Index("audit_events_subject", "subject_type", "subject_id"),
    )

    # Пусто — решение принял сервис. Ссылка гасится, а не удаляет событие:
    # ушедший сотрудник не должен уносить с собой историю решений.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Что именно решили: `book.created`, `chapter.boundaries_approved`,
    # `glossary.version_approved`. Строка, а не перечисление: виды решений
    # добавляются с каждым этапом процесса, и миграция типа на каждый из
    # них — лишняя работа ради ничего.
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    # Над чем решение: имя сущности и её идентификатор. Внешнего ключа нет
    # намеренно — событие переживает удаление объекта, иначе исчезнет
    # ровно то, ради чего журнал заводили.
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))

    # Основание и подробности: причина, прежнее и новое значение, номер
    # версии. Состав разный у каждого вида решения, поэтому JSONB.
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
