"""Прогон перевода и редакции блока.

Перевод больше не лежит в той же строке, что и исходник, и не
перезаписывается. Каждый ответ модели, совпадение с памятью и правка человека
— новая неизменяемая редакция блока, а какая из них сейчас считается текстом
книги, знает блок (`Block.current_revision_id`). «Перевести заново» поэтому
не может ничего потерять: прежняя редакция остаётся на месте, новая лежит
рядом вариантом, пока её не примут.

Прогон отвечает на вопрос, откуда редакция взялась: какая модель, какая
версия промпта, какая версия глоссария, по какой версии мастера. Состояние
прогона живёт в его задании (`TranslationJob`): их два разных факта — что
переводили и как идёт работа, — но состояние у них одно, и второй его копии
быть не должно.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey
from app.models.review import EditReason


class RunKind(str, enum.Enum):
    DRAFT = "draft"  # всё, что в главе ещё не переведено
    RETRANSLATE = "retranslate"  # выбранные блоки — вариантом рядом с текущей редакцией


class RevisionStage(str, enum.Enum):
    """На каком этапе процесса появилась редакция."""

    DRAFT = "draft"  # черновой перевод
    WORKING = "working"  # после подтверждённого исправления или редактуры
    FINAL_CANDIDATE = "final_candidate"  # кандидат в выпуск


class RevisionOrigin(str, enum.Enum):
    MODEL = "model"  # ответ модели
    MEMORY = "memory"  # готовый перевод того же текста: память или другой блок книги
    HUMAN = "human"  # написал человек
    # Защищённое содержимое: листинг и то, в чём нечего переводить, переносится
    # знак в знак и в модель не уходит вовсе.
    COPY = "copy"


class TranslationRun(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Один запуск перевода главы — неизменяемое «чем и по чему переводили»."""

    __tablename__ = "translation_runs"
    __table_args__ = (
        Index("translation_runs_chapter", "chapter_id", "created_at"),
        # Обход гейта без причины — это решение, которого никто не принимал.
        CheckConstraint(
            "NOT ignore_terminology OR bypass_reason IS NOT NULL",
            name="translation_run_bypass_reason",
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Версия мастера, которую переводим. Появилась новая — прогон прекращается:
    # продолжать значит переводить текст, которого в главе больше нет.
    master_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapter_masters.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[RunKind] = mapped_column(
        Enum(RunKind, name="translation_run_kind", native_enum=True), nullable=False
    )

    # Чем переводили. Записывается при запуске, а не берётся из настроек при
    # показе: настройки меняются, а прогон — исторический факт.
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)

    # По какой версии глоссария. Пусто — только при обходе гейта, когда
    # действующей версии нет. Проверка отложена до фиксации: при удалении книги
    # версии и прогоны уходят каскадом в порядке, которого никто не обещал.
    glossary_version_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_versions.id", deferrable=True, initially="DEFERRED"),
    )
    # Обход гейта: только администратор и только с причиной. Такой прогон
    # виден в выпуске — его блоки подлежат повторной проверке.
    ignore_terminology: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bypass_reason: Mapped[str | None] = mapped_column(Text)

    # Что переводить заново: `[{"block_id", "base_revision_id"}]`. У черновика
    # пусто — он берёт всё, у чего нет текущей редакции.
    selection: Mapped[list[dict[str, Any]]] = mapped_column(
        postgresql.JSONB, nullable=False, default=list
    )

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Итоги. Расход — нарастающим итогом после каждой пачки: прогон, упавший на
    # десятой, оставляет девять оплаченных в учёте.
    blocks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    from_model: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    from_memory: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    copied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Блоки, ответ по которым отвергнут: `[{"block_id", "code", "reason"}]`.
    # Они остаются без редакции, и прогон не пытается взять их снова.
    rejections: Mapped[list[dict[str, Any]]] = mapped_column(
        postgresql.JSONB, nullable=False, default=list
    )

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TranslationRevision(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Одна редакция перевода блока.

    Содержимое не меняется никогда, и держит это сама база: триггер
    `translation_revisions_immutable` отвергает обновление — даже мимо этого
    кода. Удаляется редакция только вместе с блоком.
    """

    __tablename__ = "translation_revisions"
    __table_args__ = (
        UniqueConstraint("block_id", "revision_no", name="translation_revision_no"),
        # Прогон, повторивший пачку после сбоя, не создаст второй редакции того
        # же блока: операции рабочего обязаны быть идемпотентными.
        Index(
            "translation_revision_run_block",
            "run_id",
            "block_id",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
    )

    block_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[RevisionStage] = mapped_column(
        Enum(RevisionStage, name="revision_stage", native_enum=True), nullable=False
    )
    origin: Mapped[RevisionOrigin] = mapped_column(
        Enum(RevisionOrigin, name="revision_origin", native_enum=True), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Пусто только у правки человека: у неё нет прогона, а есть автор.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_runs.id", ondelete="CASCADE"),
    )
    # Редакция, относительно которой создана эта.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="CASCADE"),
    )

    # Откуда взят готовый перевод. Обе ссылки обнуляются, а редакция остаётся:
    # запись памяти можно удалить, а текст редакции от этого не изменится.
    memory_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_units.id", ondelete="SET NULL"),
    )
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="SET NULL"),
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Зачем правили стиль; пусто у всего, что не литературная правка.
    edit_reason: Mapped[EditReason | None] = mapped_column(
        Enum(EditReason, name="edit_reason", native_enum=True)
    )
    # Замечание, по которому внесена правка, если оно было.
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("issues.id", deferrable=True, initially="DEFERRED"),
    )


class ObjectVerification(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Отметка «проверено технически» у объекта.

    Отметка относится к тому, что проверяли: сумма объекта и редакции его
    блоков свёрнуты в `content_hash`. Изменилось что угодно из этого — отметка
    перестаёт действовать сама, снимать её некому и незачем. Строка не
    меняется: новая проверка — новая строка, и видно, кто проверял раньше.
    """

    __tablename__ = "object_verifications"
    __table_args__ = (Index("object_verifications_latest", "object_id", "created_at"),)

    object_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
