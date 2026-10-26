"""Мастер главы — неизменяемый снимок её исходного текста.

Из исходника создаётся отдельный мастер без исправлений и
переформулирования. Он не правится никогда: ошибка извлечения
исправляется новой версией, авторская ошибка в тексте — замечанием, а не
молчаливой правкой. Операции «изменить текст мастера» в сервисе нет вовсе.

Версия хранит упорядоченный список своих блоков и объектов и контрольную
сумму по ним. Этого достаточно, чтобы восстановить любую версию целиком и
убедиться, что она не изменилась: блоки и объекты неизменяемы, а списки и
сумма пишутся один раз.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class ChapterMaster(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "chapter_masters"
    __table_args__ = (UniqueConstraint("chapter_id", "version", name="chapter_master_version"),)

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Версия, которую эта заменила. У первой — пусто.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("chapter_masters.id", ondelete="SET NULL")
    )
    # Почему понадобилась новая версия. У первой причины нет — она первая;
    # у каждой следующей причина обязательна: версия мастера без причины —
    # это правка исходника, о которой никто не знает.
    reason: Mapped[str | None] = mapped_column(Text)

    # Откуда извлечено: файл, версия разбора и границы главы на тот момент.
    # Проверка отложена до фиксации — по той же причине, что у главы:
    # немедленная споткнулась бы о каскадное удаление проекта.
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
        index=True,
    )
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    boundary_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)

    # Блоки версии по порядку. Список, а не таблица связей: он пишется один
    # раз и не меняется, а читается всегда целиком и в этом порядке.
    block_ids: Mapped[list[str]] = mapped_column(postgresql.JSONB, nullable=False)
    # Объекты версии по порядку — где каждый стоит и из чего состоит:
    # `{"id", "at", "blocks", "caption", "label"}`. `at` — сколько блоков
    # версии стоит перед объектом, `blocks` — блоки-содержимое (ячейки
    # таблицы, текст листинга), `caption` — блок подписи. Всё это у одного
    # и того же объекта в разных версиях может отличаться, поэтому хранится
    # здесь, а не у объекта.
    objects: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)
    # SHA-256 по блокам и объектам версии — см. `master_checksum`.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Человек проверил, что извлечено верно. До этого по мастеру не
    # переводят: ошибку извлечения дешевле поймать здесь, чем в переводе.
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def block_count(self) -> int:
        return len(self.block_ids)

    @property
    def object_count(self) -> int:
        return len(self.objects)

    @property
    def label(self) -> str:
        """`v2` — так версию называют в переписке и в журнале."""
        return f"v{self.version}"
