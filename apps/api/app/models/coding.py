"""Счётчики постоянных кодов: BK01, CH03, B0042, FIG001, ERR-0001.

Коды книг, глав, блоков, объектов и замечаний попадают в документы, в
переписку и в номер ошибки целиком (`BK01-CH03-ERR-0001`). Поэтому к ним
два требования, которых нет у обычных идентификаторов: номер выдаёт
только сервер, и выданный номер не достаётся никому второй раз.

Максимум по существующим записям плюс единица этого не даёт: два
одновременных запроса прочитают одно и то же «сто сорок» и оба запишут
«сто сорок один». Отдельный счётчик позволяет выдать номер одним
запросом `INSERT … ON CONFLICT DO UPDATE … RETURNING`, где увеличение и
чтение происходят атомарно, а второй запрос ждёт завершения первого.

Счётчик на каждую область: у книги своя нумерация глав, у главы — своя
нумерация блоков и замечаний. Поэтому ключ составной: вид кода плюс
владелец нумерации.
"""

import enum
import uuid

from sqlalchemy import Enum, Integer, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class CodeKind(str, enum.Enum):
    """Что нумеруем.

    Перечислением, а не строкой: набор кодов задан процессом из 24 этапов
    и не пополняется произвольно, а опечатка в виде кода выдала бы вторую
    независимую нумерацию того же самого.
    """

    BOOK = "book"  # BK01 — в пределах организации
    CHAPTER = "chapter"  # CH01 — в пределах книги
    BLOCK = "block"  # B0001 — в пределах главы
    # Объекты — у каждого вида своя нумерация в пределах главы, как в
    # самой книге: FIG001, TBL001, EQ001, CODE001.
    FIGURE = "figure"
    TABLE = "table"
    EQUATION = "equation"
    CODE = "code"
    ISSUE = "issue"  # ERR-0001 — в пределах главы


class CodeCounter(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Последний выданный номер для одной области нумерации.

    `owner_id` — тот, внутри кого нумерация сквозная: организация для
    книг, книга для глав, глава для блоков и замечаний. Внешнего ключа на
    него нет намеренно: владельцы разных видов лежат в разных таблицах, а
    счётчик обязан пережить удаление владельца — иначе удалённая и заново
    созданная глава начнёт нумерацию сначала и выдаст уже использованные
    номера замечаний.
    """

    __tablename__ = "code_counters"
    __table_args__ = (UniqueConstraint("kind", "owner_id", name="code_counter_scope"),)

    kind: Mapped[CodeKind] = mapped_column(
        Enum(CodeKind, name="code_kind", native_enum=True), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)

    # Последний выданный номер. Следующий получается увеличением на единицу
    # в том же запросе, которым он и читается.
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
