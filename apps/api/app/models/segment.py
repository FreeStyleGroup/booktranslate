"""Сегмент — единица перевода и единица проверки.

Документ хранится не сплошным текстом, а сегментами: только так можно
показать редактору, что именно проверено, подставить повтор из памяти
переводов и указать, в каком месте разошлись числа. Оценки качества живут
рядом с сегментом, потому что запрашиваются вместе с ним всегда.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class SegmentStatus(str, enum.Enum):
    NEW = "new"  # разобран, не переведён
    MACHINE = "machine"  # перевод модели, человек не смотрел
    MEMORY = "memory"  # подставлен из памяти переводов
    EDITED = "edited"  # правил человек
    APPROVED = "approved"  # принят редактором
    FLAGGED = "flagged"  # проверка нашла проблему


class SegmentKind(str, enum.Enum):
    """Роль сегмента в документе.

    Заголовок, подпись к рисунку и предупреждение переводятся по-разному:
    у заголовка свои правила краткости, у предупреждения цена ошибки выше
    всего. Тип известен после разбора исходника и влияет и на промпт, и на
    строгость проверок.
    """

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    CAPTION = "caption"
    WARNING = "warning"
    CODE = "code"


class Segment(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "segments"
    __table_args__ = (
        # Порядковый номер внутри документа уникален: по нему сегменты
        # показываются и на него ссылаются правки.
        UniqueConstraint("document_id", "position", name="document_position"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[SegmentKind] = mapped_column(
        Enum(SegmentKind, name="segment_kind", native_enum=True),
        nullable=False,
        default=SegmentKind.PARAGRAPH,
    )
    status: Mapped[SegmentStatus] = mapped_column(
        Enum(SegmentStatus, name="segment_status", native_enum=True),
        nullable=False,
        default=SegmentStatus.NEW,
        index=True,
    )

    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_text: Mapped[str | None] = mapped_column(Text)

    # Где сегмент стоял в исходнике: номер страницы, раздел, путь в разметке.
    # Свободная структура, потому что у PDF, DOCX и XLIFF она разная, а
    # заводить под каждый формат свои колонки — плодить пустоты.
    source_location: Mapped[dict[str, Any] | None] = mapped_column(postgresql.JSONB)

    # Итог проверок: расхождение чисел, нарушение глоссария, протечка
    # исходного языка, длина. Список проверок будет расти, и каждая новая
    # не должна требовать миграции.
    quality: Mapped[dict[str, Any] | None] = mapped_column(postgresql.JSONB)
    quality_score: Mapped[float | None] = mapped_column(Float, index=True)

    # Откуда взялся перевод: имя модели или «memory» — чтобы через полгода
    # можно было сказать, какой моделью переведён конкретный том.
    translation_source: Mapped[str | None] = mapped_column(String(120))
