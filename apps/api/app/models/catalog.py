"""Каталог терминов: что бюро уже выяснило про незнакомые слова.

Каталог — не словарь. Словарь (`glossary_terms`) хранит **решения**: как
этот заказчик называет эту вещь, и это требование к переводу. Каталог хранит
**справки**: что такое `slippage`, откуда это известно и какой перевод
предлагают отраслевые источники. Справка не обязывает ни к чему — решение по
ней принимает человек, и только оно попадает в словарь.

Смысл отдельной таблицы в том, что справка переживает книгу. Кандидаты в
термины живут в документе и вместе с ним заканчиваются; выяснив однажды, что
за `basis risk`, бюро обязано знать это и в следующей книге, и через год, и
в чужом проекте той же организации. Иначе за одно и то же платят столько
раз, сколько раз слово встретится в работе.

Ненайденное записывается наравне с найденным. «Мы искали и не нашли» — это
тоже знание: без него каждая новая книга снова пойдёт в сеть за словом,
которого там нет, и снова потратит на это время и деньги.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, String, Text, UniqueConstraint, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.memory import GlossaryEntryKind
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class CatalogEntry(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Справка по одному термину в одной языковой паре."""

    __tablename__ = "catalog_entries"
    __table_args__ = (
        # Одна справка на термин в языковой паре организации. Каталог общий
        # для всего бюро, а не проектный: справка «что такое basis risk» от
        # заказчика не зависит — от него зависит решение, а оно в словаре.
        UniqueConstraint(
            "organization_id",
            "source_language",
            "target_language",
            "source_term_normalized",
            name="catalog_entry_term",
        ),
    )

    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)

    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    source_term_normalized: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    # Нашлось ли вообще. Ложь — это результат, а не пустая строка: по ней
    # видно, что искать второй раз незачем.
    found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Перевод, который предлагают источники. Предложение, а не решение:
    # в словарь он попадёт только через человека.
    suggested_target: Mapped[str | None] = mapped_column(String(300))

    # Что это такое своими словами. Главная ценность справки: перевод без
    # понимания предмета — это подстановка, и ошибается она молча.
    definition: Mapped[str | None] = mapped_column(Text)

    # Расшифровка сокращения на языке оригинала: PLC → programmable logic
    # controller. Отдельно от определения, потому что в перевод она уходит
    # по своему правилу — при первом употреблении.
    expansion: Mapped[str | None] = mapped_column(String(300))

    kind: Mapped[GlossaryEntryKind] = mapped_column(
        Enum(GlossaryEntryKind, name="glossary_entry_kind", native_enum=True),
        nullable=False,
        default=GlossaryEntryKind.TERM,
    )

    # Источники: список из заголовка и адреса. Без них справка — это мнение,
    # а спор о термине через месяц начинается заново.
    #
    # Колонка названа `sources`, а не `references`: последнее — зарезервированное
    # слово SQL, и любой запрос, написанный руками мимо SQLAlchemy, спотыкался
    # бы на нём.
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        postgresql.JSONB, nullable=False, default=list
    )

    # Кто отвечал: имя модели, ходившей в сеть, или «offline». По нему видно,
    # что перепроверять после смены источника.
    looked_up_by: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # Когда справку получили. Отдельно от `updated_at`: примечание к записи
    # человек правит и не выходя в сеть, а устаревает именно поиск.
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
