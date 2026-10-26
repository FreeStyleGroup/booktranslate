"""Кандидаты в словарь: результат терминологического прохода по главе.

Кандидат — это не термин, а вопрос к человеку: «вот это слово встречается в
книге сорок раз, как его называть?». Хранить их надо именно в базе, а не
считать заново при каждом открытии списка, по двум причинам.

Во-первых, решение стоит времени: двести терминов книги редактор разбирает
не за один присест, и список обязан пережить закрытую вкладку. Во-вторых,
отклонённое должно остаться отклонённым: если повторный проход снова
покажет те же двести строк, включая уже отвергнутые, работу придётся делать
заново, и на второй раз её просто не сделают.

Кандидаты собираются по главе — по тексту её мастера. Проход по документу
остался от прежнего контура и уходит вместе с сегментами: до тех пор у
кандидата ровно один владелец — документ или глава, и это держит база.
"""

import enum
import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.memory import GlossaryEntryKind
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class TermCandidateStatus(str, enum.Enum):
    NEW = "new"  # ждёт решения
    ACCEPTED = "accepted"  # заведён в глоссарий
    REJECTED = "rejected"  # не термин, больше не показывать


class TermCandidate(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "term_candidates"
    __table_args__ = (
        # Один кандидат на владельца. Повторный проход обновляет частоту, а
        # не плодит вторую строку с тем же словом.
        UniqueConstraint(
            "document_id", "source_term_normalized", name="term_candidate_in_document"
        ),
        UniqueConstraint("chapter_id", "source_term_normalized", name="term_candidate_in_chapter"),
        CheckConstraint("num_nonnulls(document_id, chapter_id) = 1", name="term_candidate_owner"),
    )

    # Прежний владелец — разобранный на сегменты документ.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        index=True,
    )

    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    source_term_normalized: Mapped[str] = mapped_column(String(300), nullable=False)

    kind: Mapped[GlossaryEntryKind] = mapped_column(
        Enum(GlossaryEntryKind, name="glossary_entry_kind", native_enum=True),
        nullable=False,
        default=GlossaryEntryKind.TERM,
    )
    status: Mapped[TermCandidateStatus] = mapped_column(
        Enum(TermCandidateStatus, name="term_candidate_status", native_enum=True),
        nullable=False,
        default=TermCandidateStatus.NEW,
        index=True,
    )

    # Сколько раз встретилось. Это и порядок разбора, и ответ на вопрос
    # «стоит ли вообще тратить на него время».
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Кусок текста вокруг первого вхождения. Решать по голому списку слов
    # нельзя: `head` — это и «головка», и «оголовок», и различает их контекст.
    sample: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Место первого вхождения: номер сегмента документа или место блока в
    # мастере главы. В рабочих реестрах первое вхождение указывают всегда:
    # спор о термине решается возвратом к этому месту, а не пересказом.
    first_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Блок первого вхождения — у кандидата главы. Ссылка гасится, а не
    # уносит кандидата: блок уходит только вместе с главой, но решение по
    # термину не должно зависеть от того, жив ли пример.
    first_block_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="SET NULL")
    )

    # Расшифровка аббревиатуры, найденная в самом тексте. Уезжает в примечание
    # к термину: переводчик, знающий, что за PLC, не напишет «ПЛК-контроллер».
    expansion: Mapped[str | None] = mapped_column(String(300))

    # Что получилось из принятого кандидата. SET NULL, а не CASCADE: удаление
    # термина из словаря не должно стирать след того, что решение принималось.
    glossary_term_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_terms.id", ondelete="SET NULL"),
    )


class TerminologyPass(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Проход по главе за кандидатами: по какой версии мастера и с каким итогом.

    Без этой записи «кандидатов нет» значит одно из двух — проход был и
    ничего не нашёл, или прохода не было вовсе, — и различить их нельзя.
    Именно эта дыра позволяла начать перевод, ни разу не собрав термины.
    Версия мастера хранится потому, что проход по прежней версии ничего не
    говорит о тексте новой: в ней могли появиться абзацы с новыми словами.
    """

    __tablename__ = "terminology_passes"

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    master_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapter_masters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # С каким порогом шли: проход с порогом пять и проход с порогом два —
    # разные проходы, и второй находит больше.
    min_frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    # Сколько кандидатов нашлось в этот раз, включая уже решённые.
    found: Mapped[int] = mapped_column(Integer, nullable=False)
