"""Кандидаты в словарь: результат терминологического прохода по документу.

Кандидат — это не термин, а вопрос к человеку: «вот это слово встречается в
книге сорок раз, как его называть?». Хранить их надо именно в базе, а не
считать заново при каждом открытии списка, по двум причинам.

Во-первых, решение стоит времени: двести терминов книги редактор разбирает
не за один присест, и список обязан пережить закрытую вкладку. Во-вторых,
отклонённое должно остаться отклонённым: если повторный проход снова
покажет те же двести строк, включая уже отвергнутые, работу придётся делать
заново, и на второй раз её просто не сделают.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, UniqueConstraint
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
        # Один кандидат на документ. Повторный проход обновляет частоту, а не
        # плодит вторую строку с тем же словом.
        UniqueConstraint(
            "document_id", "source_term_normalized", name="term_candidate_in_document"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
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

    # Сколько раз встретилось в документе. Это и порядок разбора, и ответ на
    # вопрос «стоит ли вообще тратить на него время».
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Кусок текста вокруг первого вхождения. Решать по голому списку слов
    # нельзя: `head` — это и «головка», и «оголовок», и различает их контекст.
    sample: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Номер сегмента, где термин встретился впервые. В рабочих реестрах
    # первое вхождение указывают всегда: спор о термине решается возвратом
    # к этому месту, а не пересказом по памяти.
    first_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Расшифровка аббревиатуры, найденная в самом тексте. Уезжает в примечание
    # к термину: переводчик, знающий, что за PLC, не напишет «ПЛК-контроллер».
    expansion: Mapped[str | None] = mapped_column(String(300))

    # Что получилось из принятого кандидата. SET NULL, а не CASCADE: удаление
    # термина из словаря не должно стирать след того, что решение принималось.
    glossary_term_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_terms.id", ondelete="SET NULL"),
    )
