"""Документ — один файл, загруженный в проект.

Документ проходит путь от загрузки до готового перевода, и его состояние
нужно видеть в интерфейсе, поэтому статус — колонка, а не вычисление по
сегментам: пересчитывать его на каждый запрос списка из тысячи документов
дорого, а «загружен, но ещё не разобран» по сегментам вообще не определить.
"""

import enum
import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"  # файл принят, ничего с ним ещё не делали
    PARSING = "parsing"  # разбираем структуру
    PARSED = "parsed"  # разобран на сегменты, готов к переводу
    TRANSLATING = "translating"  # перевод идёт
    REVIEW = "review"  # переведён, ждёт человека
    DONE = "done"  # проверен и принят
    FAILED = "failed"  # сломался; причина — в error


class SourceFormat(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    MARKDOWN = "markdown"
    XLIFF = "xliff"
    EPUB = "epub"
    TXT = "txt"


class Document(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Один и тот же файл не заводится в проекте дважды. Проверка перед
        # вставкой отсеивает повтор в обычном случае, но два одновременных
        # запроса пройдут её оба — гарантию даёт только ограничение в базе.
        # Частичное: у документа без подсчитанной суммы ограничивать нечего.
        Index(
            "documents_project_content_hash",
            "project_id",
            "content_hash",
            unique=True,
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # Имя файла таким, каким его дал человек. Хранится отдельно от названия:
    # название потом правят, а по имени файла ищут «тот самый», который
    # присылали в переписке.
    original_filename: Mapped[str | None] = mapped_column(String(255))
    source_format: Mapped[SourceFormat] = mapped_column(
        Enum(SourceFormat, name="document_source_format", native_enum=True), nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", native_enum=True),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        index=True,
    )

    # Где лежит исходный файл. Строка, а не путь на диске: сегодня это
    # локальный каталог, завтра — объектное хранилище, и модель об этом
    # знать не должна.
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    # Контрольная сумма исходника: по ней видно, что тот же файл загрузили
    # повторно, и не нужно платить за повторный разбор и перевод.
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    error: Mapped[str | None] = mapped_column(Text)
