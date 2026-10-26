"""Глава книги и её утверждённые границы.

До перевода у главы должны быть утверждены начало, конец и заголовки.
Без этого «глава 3» — понятие из головы переводчика: разбор файла заново
сдвинет её на абзац, и замечания, привязанные к ней, повиснут в воздухе.

Границы выражены номерами блоков основного источника в порядке разбора —
`source_start` включительно, `source_end` исключительно. Номера осмыслены
только вместе с файлом и версией разбора, поэтому оба хранятся рядом:
тот же файл, разобранный другой версией, может дать другую нарезку.
"""

import enum
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey

# Приставка кода главы: `CH03` входит в номера блоков и замечаний.
CODE_PREFIX = "CH"


class BoundaryStatus(str, enum.Enum):
    DRAFT = "draft"  # предложено или изменено, решения ещё нет
    APPROVED = "approved"  # человек утвердил — можно извлекать мастер


class ChapterOrigin(str, enum.Enum):
    """Откуда взялись границы.

    Нужно для того же, для чего журнал решений: предложенное по заголовкам
    и выставленное руками проверяют по-разному, и по готовой главе должно
    быть видно, какой из случаев перед глазами.
    """

    HEADING = "heading"  # по заголовкам верхнего уровня
    PATH = "path"  # по файлам EPUB, когда заголовков нет
    PAGE = "page"  # PDF без заголовков: одна глава, разделы по страницам
    WHOLE = "whole"  # ни заголовков, ни страниц — документ целиком
    MANUAL = "manual"  # разделена или объединена человеком


class Chapter(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Глава: постоянный код, место в книге и утверждённые границы.

    Код и место — разные вещи. Место (`ordinal`) меняется, когда главу
    выше разделяют или объединяют. Код (`CH03`) не меняется никогда: он
    входит в номера блоков и замечаний, и перенумерация разорвала бы их
    связь с главой.

    Номер кода выдаётся при утверждении, а не при предложении: предложение
    можно отбросить и повторить, а выданный номер второй записи не
    достаётся — иначе после двух попыток первая глава книги звалась бы
    `CH13`. Утверждают по порядку книги, поэтому `CH03` — это третья глава
    на момент, когда её границы приняли.
    """

    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "number", name="chapter_number"),
        # Место уникально, но проверяется в конце транзакции: при разделении
        # главы все нижестоящие сдвигаются на одно место, и на середине
        # сдвига две главы на миг стоят на одном.
        UniqueConstraint(
            "book_id", "ordinal", name="chapter_ordinal", deferrable=True, initially="DEFERRED"
        ),
        CheckConstraint("source_end > source_start", name="chapter_range"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Файл, по номерам блоков которого заданы границы. Удалить его, пока
    # на нём держатся главы, нельзя: границы потеряли бы смысл молча.
    #
    # Проверка отложена до фиксации транзакции. Каскадные удаления в
    # Postgres — отдельные внутренние запросы, и немедленная проверка (и
    # RESTRICT, и NO ACTION) срабатывает в конце каждого: при удалении
    # проекта каскад до документов доходит раньше, чем до глав его книг, и
    # удаление падало бы на собственных главах. К фиксации главы уже убраны.
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
        index=True,
    )

    # Пусто, пока границы не утверждены ни разу.
    number: Mapped[int | None] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))

    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # Где глава начинается — так, как это увидит человек: файл EPUB,
    # страница PDF, строка Markdown.
    locator: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    # Разделы главы: подзаголовки с числом блоков каждого вида. По ним
    # глава делится и сливается без повторного разбора файла, и из них же
    # складывается её состав. Снимок предложения, а не живая структура:
    # блоки с постоянными кодами появятся при извлечении мастера.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)

    origin: Mapped[ChapterOrigin] = mapped_column(
        Enum(ChapterOrigin, name="chapter_origin", native_enum=True), nullable=False
    )
    boundary_status: Mapped[BoundaryStatus] = mapped_column(
        Enum(BoundaryStatus, name="boundary_status", native_enum=True),
        nullable=False,
        default=BoundaryStatus.DRAFT,
    )
    # Растёт при каждом изменении утверждённых границ: проверки, сделанные
    # по прежней версии, по ней и узнают, что устарели.
    boundary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Последнее утверждение. История утверждений — в журнале решений.
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def inventory(self) -> dict[str, int]:
        """Состав главы: сколько в ней блоков каждого вида.

        Считается из разделов, а не хранится: вторая запись того же
        значения разошлась бы с первой при первом же разделении главы.
        """
        total: Counter[str] = Counter()

        for section in self.sections:
            total.update(section["kinds"])

        return dict(total)

    @property
    def code(self) -> str | None:
        """`CH03` — или ничего, пока границы не утверждены ни разу."""
        return None if self.number is None else f"{CODE_PREFIX}{self.number:02d}"
