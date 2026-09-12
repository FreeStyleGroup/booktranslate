"""Общий словарь площадки: термины, которыми пространства делятся.

Это не обучение модели, и это лучше обучения: термин подставляется в
запрос при переводе, действует мгновенно, откатывается одной строкой, и у
каждого видно, откуда он взялся. Модель не дообучается ни на чём.

Делятся только термины — слово и его перевод. Память переводов остаётся
внутри пространства: в ней фразы из книги заказчика, то есть чужой текст
под авторским правом, часто неопубликованный.

В общий словарь запись попадает не сама: её одобряет администратор
площадки из загрузки, по которой пространство дало разрешение. У записи
обязательна тематика — без неё «bank» из банковского словаря лез бы в
книгу про реки.
"""

import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.memory import GlossaryEntryKind
from app.models.mixins import TimestampMixin, UUIDPrimaryKey


class SharedTerm(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "shared_terms"
    __table_args__ = (
        # Один термин на тематику и языковую пару: второе одобрение того же
        # слова уточняет перевод, а не заводит соседа.
        UniqueConstraint(
            "subject",
            "source_language",
            "target_language",
            "source_term_normalized",
            name="shared_term_in_subject",
        ),
    )

    subject: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)

    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    source_term_normalized: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    target_term: Mapped[str] = mapped_column(String(300), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    kind: Mapped[GlossaryEntryKind] = mapped_column(
        Enum(GlossaryEntryKind, name="glossary_entry_kind", native_enum=True),
        nullable=False,
        default=GlossaryEntryKind.TERM,
    )

    # Откуда пришло и кто одобрил. SET NULL: уход пространства или
    # администратора не должен стирать сам термин — он уже общий.
    origin_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL")
    )
    origin_term_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("glossary_terms.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
