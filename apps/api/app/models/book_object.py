"""Специальные объекты книги: рисунки, таблицы, формулы и листинги кода.

Объект отделён от текстовых блоков: у рисунка нет текста, у таблицы текст
есть, но в ячейках со своими координатами, формулу и код нельзя
переформулировать вовсе. Поэтому у объекта свой постоянный код (`CH03-FIG001`)
и своя контрольная сумма, а текст, который в нём переводится, — ячейки
таблицы, листинг, подпись — живёт в обычных блоках с обычными кодами.

Объект неизменяем, как и блок: изменилось содержимое — это новый объект с
новым кодом и ссылкой на прежний. Какие блоки составляют объект в той или
иной версии мастера и где он стоит, хранит сама версия — см.
`ChapterMaster.objects`.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class ObjectType(str, enum.Enum):
    FIGURE = "figure"
    TABLE = "table"
    EQUATION = "equation"
    CODE = "code"


# Приставки кодов. Нумерация у каждого вида своя — так их и называют в
# книге: рисунок третий, таблица первая.
CODE_PREFIXES = {
    ObjectType.FIGURE: "FIG",
    ObjectType.TABLE: "TBL",
    ObjectType.EQUATION: "EQ",
    ObjectType.CODE: "CODE",
}


class BookObject(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Рисунок, таблица, формула или листинг главы с постоянным кодом.

    Код не связан с номером в книге: «Рисунок 3.2» после перенумерации
    становится «Рисунком 3.3», а `CH03-FIG001` остаётся собой. Номер из
    подписи хранится отдельно (`label`) — по нему находятся упоминания.
    """

    __tablename__ = "book_objects"
    __table_args__ = (
        UniqueConstraint("chapter_id", "type", "number", name="book_object_number"),
        Index("book_objects_current", "chapter_id", "active", "type"),
    )

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Версия мастера, в которой объект появился впервые.
    master_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapter_masters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Объект, из которого этот получился при новой версии мастера.
    parent_object_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("book_objects.id", ondelete="SET NULL")
    )

    type: Mapped[ObjectType] = mapped_column(
        Enum(ObjectType, name="object_type", native_enum=True), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_location: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)

    # То, чего нет в блоках: сетка таблицы с объединёнными ячейками, запись
    # формулы как есть и её нормализованная сумма, язык листинга,
    # изображения рисунка с их суммами. Состав зависит от вида.
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    # SHA-256 содержимого: для рисунка — по байтам изображений, для
    # таблицы — по сетке и тексту ячеек, для формулы — по записи как есть,
    # для листинга — по его тексту знак в знак.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    # Ниже — состояние в текущей версии мастера, как место у блока.
    # Прежние версии показываются по своему списку, а не по этим полям.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    caption_block_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="SET NULL")
    )
    # Номер из подписи или из самой формулы: «3.2».
    label: Mapped[str | None] = mapped_column(String(40))

    @property
    def code(self) -> str:
        """`FIG001`: три цифры — объектов одного вида в главе меньше тысячи."""
        return f"{CODE_PREFIXES[self.type]}{self.number:03d}"


class ReferenceKind(str, enum.Enum):
    """Как блок ссылается на объект.

    Гиперссылка надёжна: автор книги сам указал, куда она ведёт. Упоминание
    по номеру («см. рис. 3.2») находится по тексту и верно ровно настолько,
    насколько верна нумерация в книге.
    """

    LINK = "link"
    LABEL = "label"


class ObjectReference(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Упоминание объекта в тексте блока: «см. рис. 3.2».

    Производные данные, а не решение человека: текст блока неизменяем, и
    его упоминания — функция текста и текущего набора объектов книги.
    Поэтому они пересчитываются целиком при каждом извлечении мастера.
    """

    __tablename__ = "object_references"
    __table_args__ = (UniqueConstraint("block_id", "object_id", name="object_reference_pair"),)

    block_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[ReferenceKind] = mapped_column(
        Enum(ReferenceKind, name="object_reference_kind", native_enum=True), nullable=False
    )
    # Как объект упомянут — «Figure 3.2» или текст ссылки.
    phrase: Mapped[str] = mapped_column(String(200), nullable=False)
