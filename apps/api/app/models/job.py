"""Задание на перевод главы — то, что делается без человека.

Книга на четыреста страниц переводится часами, и держать ради этого
открытой вкладку нельзя: человек ставит книгу в очередь и уходит. Дальше
работает отдельный процесс, а по готовности приходит уведомление.

Очередь в базе, а не в брокере сообщений. Причина не в экономии: Postgres
здесь уже есть, `FOR UPDATE SKIP LOCKED` даёт ровно то, что нужно от
очереди — задание достаётся одному рабочему, — а очередь в базе видно
теми же запросами, что и всё остальное. Сорвавшееся задание не исчезает
в чужой системе, а лежит строкой с причиной отказа. Брокер понадобится
тогда, когда одного Postgres перестанет хватать, и это будет видно по
числам, а не предполагаться заранее.

Счётчики `items_total` и `items_done` — факты запуска, а не копия состояния
главы. Они отвечают на вопрос «сколько эта работа сделала» и разойтись с главой
не могут: кроме самого запуска их никто не меняет.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.chapter import Chapter
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class JobKind(str, enum.Enum):
    """Что за работа стоит в очереди.

    Очередь одна на всё долгое: перевод, а дальше проверки, регрессия, сборка и
    вёрстка. Рабочий выбирает обработчик по этому полю.
    """

    CHAPTER = "chapter"  # прогон перевода главы
    QA = "qa"  # прогон проверки главы


class JobState(str, enum.Enum):
    WAITING = "waiting"  # в очереди, никто не взял
    RUNNING = "running"  # рабочий взял и переводит
    DONE = "done"  # книга переведена целиком
    FAILED = "failed"  # сорвалось; причина — в error
    CANCELLED = "cancelled"  # остановлено человеком


# Состояния, в которых задание занимает очередь. По ним же строится
# ограничение «одна книга — одно живое задание».
LIVE = (JobState.WAITING, JobState.RUNNING)


class TranslationJob(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "translation_jobs"
    __table_args__ = (
        # Одна глава — один живой прогон: два одновременных перевода одной главы
        # заплатили бы дважды и подрались за текущую редакцию.
        Index(
            "translation_jobs_live_chapter",
            "chapter_id",
            unique=True,
            postgresql_where=text("state IN ('WAITING', 'RUNNING')"),
        ),
        # Задание выполняет ровно один прогон — того вида, какой у него указан.
        CheckConstraint(
            "(kind = 'CHAPTER' AND run_id IS NOT NULL AND qa_run_id IS NULL) "
            "OR (kind = 'QA' AND qa_run_id IS NOT NULL AND run_id IS NULL)",
            name="translation_job_has_one_run",
        ),
        # Рабочий забирает задания по состоянию и порядку поступления.
        Index("translation_jobs_queue", "state", "created_at"),
    )

    kind: Mapped[JobKind] = mapped_column(
        Enum(JobKind, name="job_kind", native_enum=True),
        nullable=False,
        default=JobKind.CHAPTER,
    )

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Глава подгружается вместе с заданием: задание показывают человеку, а ему
    # задание без названия ни о чём не говорит. Одним соединением, а не отдельным
    # запросом на строку списка.
    chapter: Mapped[Chapter] = relationship(lazy="joined")

    # Прогон, который это задание выполняет. Состояние прогона — состояние
    # этого задания: второй его копии в прогоне нет и разойтись нечему.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_runs.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    qa_run_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("qa_runs.id", ondelete="CASCADE"), unique=True
    )

    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state", native_enum=True),
        nullable=False,
        default=JobState.WAITING,
    )

    # Кто поставил в очередь — ему и уведомление. Ссылка обнуляется, а не
    # уносит задание: история работы не должна исчезать вместе с уволенным.
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Кто взял задание и когда в последний раз подавал признаки жизни.
    # Отметка ставится после каждой пачки: задание, молчащее дольше порога,
    # — это убитый рабочий, и его работу забирает другой.
    worker: Mapped[str | None] = mapped_column(String(120))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Сколько раз задание бралось в работу. Растёт и при повторе после
    # сбоя, и при перехвате у мёртвого рабочего: и то и другое — заход на
    # ту же работу, и предел у них общий.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    # Факты запуска: сколько было работы, когда взялись, и сколько сделано.
    # Повторы и совпадения с памятью считаются сделанными — они и есть сделанные,
    # просто бесплатно.
    items_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Когда ушло уведомление о готовности. Отдельной отметкой, а не флагом:
    # по ней видно, сколько задание пролежало готовым до того, как о нём
    # сообщили, — и она же не даёт отправить второй раз.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def title(self) -> str:
        """Что переводится — так, как это назовёт человек."""
        return " · ".join(part for part in (self.chapter.code, self.chapter.title) if part)

    @property
    def book_id(self) -> uuid.UUID:
        return self.chapter.book_id
