"""Блок книги — логический абзац, заголовок или пункт с постоянным кодом."""

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey

# Приставка кода блока. Полный код — с главой: `CH03-B0042`.
CODE_PREFIX = "B"


class BlockKind(str, enum.Enum):
    """Роль блока в книге.

    Заголовок, подпись к рисунку и предупреждение переводятся по-разному:
    у заголовка свои правила краткости, у предупреждения цена ошибки выше
    всего. Вид известен после разбора исходника и влияет и на промпт, и на
    строгость проверок.

    Определён здесь, а не у сегмента: сегмент — техническая часть прежнего
    контура и уходит, а вид принадлежит блоку книги. Значения хранятся в
    базе тем же типом `segment_kind`, поэтому переезд обошёлся без миграции.
    """

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    CAPTION = "caption"
    WARNING = "warning"
    CODE = "code"


class Block(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Логический абзац, заголовок или пункт главы с постоянным кодом.

    Текст блока неизменяем с момента создания. Изменился текст в новой
    версии мастера — это новый блок с новым кодом, а прежний выводится из
    действия (`active`), но остаётся: на него ссылаются старая версия
    мастера и всё, что к ней привязано. Обнови мы текст на месте, прежняя
    версия мастера потеряла бы содержимое.

    Код (`B0042`) уникален в главе и второй записи не достаётся. Место
    (`ordinal`) — порядок в текущей версии мастера и меняется вместе с ней.
    """

    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("chapter_id", "number", name="block_number"),
        # Главный запрос — текущие блоки главы по порядку.
        Index("blocks_current", "chapter_id", "active", "ordinal"),
    )

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Версия мастера, в которой блок появился впервые. В какие версии он
    # входит — знает каждая версия по своему списку блоков.
    master_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapter_masters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Блок, из которого этот получился: разделение абзаца или правка его
    # текста при новой версии мастера. Прежний код при этом не
    # переиспользуется — родство видно по этой ссылке.
    parent_block_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="SET NULL")
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[BlockKind] = mapped_column(
        Enum(BlockKind, name="block_kind", native_enum=True), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_location: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    # SHA-256 текста: по нему блоки сопоставляются при новой версии мастера.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Входит ли блок в текущую версию мастера главы.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def code(self) -> str:
        """`B0042`: четыре цифры минимум — глав длиннее тысяч блоков почти не бывает."""
        return f"{CODE_PREFIX}{self.number:04d}"


class SegmentChunk(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Часть блока, которую получает модель.

    Техническая единица, а не единица работы: смена размеров нарезки
    перекраивает части, но коды блоков не трогает. Склейка частей блока —
    ровно его текст, знак в знак.
    """

    __tablename__ = "segment_chunks"
    __table_args__ = (UniqueConstraint("block_id", "chunk_index", name="segment_chunk_index"),)

    block_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
