"""Задание на перевод книги — то, что делается без человека.

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

Счётчики `segments_total` и `segments_done` — факты запуска, а не копия
состояния документа. Они отвечают на вопрос «сколько эта работа сделала»,
и разойтись с документом не могут: кроме самого запуска их никто не
меняет.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


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
        # Одна книга — одно живое задание. Без этого двойное нажатие заводит
        # два задания на одну книгу: перевод они друг у друга не отнимут —
        # документ запирается отдельно, — но второе будет вечно упираться в
        # занятый документ и в конце концов ляжет с отказом, которого никто
        # не просил.
        Index(
            "translation_jobs_live_document",
            "document_id",
            unique=True,
            postgresql_where=text("state IN ('WAITING', 'RUNNING')"),
        ),
        # Рабочий забирает задания по состоянию и порядку поступления.
        Index("translation_jobs_queue", "state", "created_at"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

    # Факты запуска: сколько было непереведённого, когда взялись, и сколько
    # перевели. Повторы и совпадения с памятью считаются переведёнными —
    # они и есть переведённые, просто бесплатно.
    segments_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segments_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Когда ушло уведомление о готовности. Отдельной отметкой, а не флагом:
    # по ней видно, сколько задание пролежало готовым до того, как о нём
    # сообщили, — и она же не даёт отправить второй раз.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
