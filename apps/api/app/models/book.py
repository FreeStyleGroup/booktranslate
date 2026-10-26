"""Издание — книга как единица работы, а не как файл.

До сих пор единицей была `Document`: один загруженный файл. Для перевода
книги этого мало. У книги несколько исходников с разными ролями — EPUB,
из которого берут текст, и PDF, по которому сверяют вёрстку, — и между
ними должна быть формальная связь. Без неё два файла одной книги
выглядят как два независимых документа, и ничто не мешает перепутать
издания или начать перевод с визуального эталона.

Издание, а не «книга»: у одной книги бывает второе издание с другой
нумерацией глав и другими таблицами, и переводят их порознь.
"""

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class BookStatus(str, enum.Enum):
    DRAFT = "draft"  # собирается комплект исходников
    IN_PROGRESS = "in_progress"  # работа над переводом идёт
    RELEASED = "released"  # выпущена, есть утверждённая версия


# Приставка кода издания. Код уходит в номера замечаний
# (`BK01-CH03-ERR-0001`), поэтому выдаётся один раз и не меняется.
CODE_PREFIX = "BK"


class BookEdition(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Книга в работе: комплект исходников, язык, состояние.

    Хранится номер, а код (`BK01`) — его запись. Номер выдаёт счётчик по
    порядку, и он же задаёт порядок списка: строка «BK100» встала бы
    раньше «BK99», а время заведения у книг, заведённых одной транзакцией,
    совпадает до микросекунды. Храни мы и номер, и код, они были бы двумя
    записями одного значения — и однажды разошлись бы.

    Код входит в номера замечаний (`BK01-CH03-ERR-0001`), поэтому номер
    выдаётся один раз и не меняется: переименование разорвало бы связь
    между выпущенной книгой и её реестром ошибок. Уникален в пределах
    организации — два разных заказчика вправе иметь каждый свою `BK01`.

    Языковая пара хранится у издания, хотя она есть и у проекта. Проект —
    комплект работ, и в нём со временем появятся книги с другой целевой
    парой; всё, что считается по книге — глоссарий версии, память,
    манифест выпуска, — должно брать пару у книги, а не угадывать её по
    соседям.
    """

    __tablename__ = "book_editions"
    __table_args__ = (UniqueConstraint("organization_id", "number", name="book_edition_number"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(300))
    # «2-е издание, 2021» — человеческая пометка, по которой отличают
    # издания друг от друга. Разбирать её на год и номер незачем: она
    # нужна глазам, а не запросам.
    edition_label: Mapped[str | None] = mapped_column(String(200))

    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)

    status: Mapped[BookStatus] = mapped_column(
        Enum(BookStatus, name="book_status", native_enum=True),
        nullable=False,
        default=BookStatus.DRAFT,
        index=True,
    )

    @property
    def code(self) -> str:
        """`BK01`: две цифры минимум — так коды первой сотни выравниваются в
        списке, а дальше число просто растёт, без потолка в два разряда."""
        return f"{CODE_PREFIX}{self.number:02d}"


class SourceValidationResult(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Что сервис смог прочитать в загруженном файле.

    Результат нужен человеку до начала работы: PDF без текстового слоя
    переводить нельзя, и узнать об этом следует на загрузке, а не через
    час на пустом разборе.

    Одна запись на документ: файл неизменяем — повторная загрузка заводит
    новый документ, — поэтому хранить историю проверок одного и того же
    файла незачем. Перепроверка перезаписывает запись и двигает
    `updated_at`.

    Контрольной суммы здесь нет намеренно: она уже лежит в
    `documents.content_hash`, и вторая копия однажды разойдётся с первой.
    """

    __tablename__ = "source_validation_results"
    __table_args__ = (UniqueConstraint("document_id", name="source_validation_document"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Формат распознан и файл открывается разбором. Ложь означает, что
    # дальше идти некуда, какой бы ни была остальная проверка.
    format_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Текстовый слой найден. У сканированного PDF его нет, и это главная
    # причина, по которой файл не годится в основной источник.
    has_text_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # Название и автор так, как их объявляет сам файл: EPUB — в OPF,
    # PDF — в словаре сведений, DOCX — в свойствах документа. Нужны для
    # одной задачи: сличить два источника одной книги. Сравнивать их по
    # числу страниц нельзя — у EPUB страниц нет вовсе, — а по имени файла
    # бессмысленно: оно у скачанных копий произвольное.
    meta_title: Mapped[str | None] = mapped_column(String(500))
    meta_author: Mapped[str | None] = mapped_column(String(300))

    # Версия разборщика: тот же файл на новой версии читается иначе, и без
    # этой отметки нельзя понять, почему результат разошёлся с прошлым.
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)

    # Замечания разбора: пустые страницы, нераспознанные вставки, битые
    # ссылки. Список строк — JSONB, потому что набор замечаний будет
    # расти, и каждое новое не должно требовать миграции.
    warnings: Mapped[list[str]] = mapped_column(postgresql.JSONB, nullable=False, default=list)
