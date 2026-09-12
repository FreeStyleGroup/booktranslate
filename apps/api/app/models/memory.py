"""Память переводов и глоссарий.

Две разные вещи, которые часто путают.

Память переводов хранит **готовые пары** «этот исходный текст переведён вот
так». Она отвечает на вопрос «мы это уже переводили?» и экономит деньги
напрямую: точное совпадение стоит ноль, а не «дёшево». В технической
документации повторов много — серия руководств на линейку, второе издание,
перевод дельты между версиями.

Глоссарий хранит **термины** и ничего не переводит. Он отвечает на вопрос
«как у этого заказчика принято называть вот это» и работает двумя способами:
термин попадает в контекст запроса к модели и проверяется в её ответе. Без
глоссария один и тот же housing станет «корпусом» в главе 2 и «кожухом» в
главе 7, и вычитка обойдётся дороже перевода.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class TranslationUnit(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Единица памяти переводов: пара «исходник — перевод» для языковой пары."""

    __tablename__ = "translation_units"
    __table_args__ = (
        # Поиск идёт по хешу, а не по тексту: сравнивать строки на сотни
        # знаков в индексе дорого, а хеш фиксированной длины. Уникальность
        # по организации и языковой паре — одна и та же фраза у разных
        # заказчиков переводится по-разному, и смешивать их нельзя.
        UniqueConstraint(
            "organization_id",
            "source_language",
            "target_language",
            "source_hash",
            name="translation_unit_source",
        ),
    )

    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)

    # Хеш нормализованного исходника: регистр и пробелы к совпадению отношения
    # не имеют, а без нормализации «Внимание!» и «Внимание !» считались бы
    # разными фразами и оплачивались дважды.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Откуда взялся перевод: имя модели или «human». По нему видно, чему
    # доверять: правка редактора надёжнее машинного перевода, и при
    # совпадении она должна вытеснять его, а не наоборот.
    origin: Mapped[str] = mapped_column(String(120), nullable=False, default="machine")

    # Сколько раз пара пригодилась. Не статистика ради статистики: по ней
    # видно, что именно окупает память, и её же показывают заказчику как
    # обоснование скидки на повторный заказ.
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GlossaryEntryKind(str, enum.Enum):
    """Что за запись в словаре.

    Разные виды ведут себя по-разному и при подсказке модели, и при проверке
    результата, поэтому вид — колонка, а не соглашение об именовании.
    """

    TERM = "term"  # обычный термин: valve → клапан
    # Аббревиатура: ПЛК, СИЗ, HMI. Отличается регистром (у неё он значим) и
    # тем, что при первом употреблении её часто требуется раскрыть.
    ABBREVIATION = "abbreviation"
    # Не переводится вовсе: ISO, USB, PDF, названия марок и артикулы. Проверка
    # требует, чтобы строка осталась в переводе дословно.
    DO_NOT_TRANSLATE = "do_not_translate"
    # Обозначение: μ, σᵤ, W₀, LT1. В научном тексте их больше, чем терминов,
    # и ошибка в них тише всего: подменённый индекс не читается как опечатка,
    # а меняет смысл формулы. Переводу не подлежат, но требуют различения —
    # σ и σᵤ это разные вещи, и в словаре они разными записями.
    NOTATION = "notation"
    # Имя собственное: площадка (NASDAQ), модель (Ho–Stoll), фирма. Иногда
    # имеет принятую русскую форму, иногда остаётся латиницей — решает
    # человек, поэтому это отдельный разряд, а не «непереводимое».
    PROPER_NAME = "proper_name"


class GlossaryTermStatus(str, enum.Enum):
    """Насколько решение по термину устоялось.

    Разряд отвечает на вопрос «что это», статус — «договорились ли мы».
    Это разные вещи, и смешивать их нельзя: неустоявшийся термин обязан
    уходить модели подсказкой, но не имеет права помечать сегмент ошибкой —
    иначе редактор получит сотню претензий к переводу там, где спор идёт о
    самом словаре.
    """

    PROPOSED = "proposed"  # предварительно рекомендован
    CONFIRMED = "confirmed"  # подтверждён, применяется как требование
    NEEDS_REVIEW = "needs_review"  # требует перепроверки
    # Требует унификации по книге: в разных главах названо по-разному, и
    # решение принимается не по одной главе.
    NEEDS_UNIFICATION = "needs_unification"
    RETIRED = "retired"  # снят: дубликат или ошибка, в работу не идёт


class GlossaryTerm(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Запись словаря: термин, аббревиатура или непереводимое."""

    __tablename__ = "glossary_terms"
    __table_args__ = (
        # Термин уникален в пределах своей области действия. Индексов два, и
        # это не дублирование: NULL в project_id означает «для всех проектов»,
        # а Postgres считает NULL в уникальном индексе разными значениями —
        # один общий индекс пропустил бы сколько угодно копий одного и того же
        # термина организации. Поэтому для проектных терминов индекс из пяти
        # колонок, для общих — частичный, из четырёх.
        Index(
            "glossary_term_in_project",
            "organization_id",
            "project_id",
            "source_language",
            "target_language",
            "source_term_normalized",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        Index(
            "glossary_term_in_organization",
            "organization_id",
            "source_language",
            "target_language",
            "source_term_normalized",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
    )

    # Термин может быть общим для организации либо принадлежать проекту:
    # у одного заказчика «valve» — «клапан», у другого в том же бюро —
    # «вентиль», и общий словарь бюро им обоим только мешает.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )

    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)

    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    # Нормализованный вид — по нему ищут и по нему проверяют уникальность.
    # Хранится колонкой, а не вычисляется запросом: иначе индекс не работает.
    source_term_normalized: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    target_term: Mapped[str] = mapped_column(String(300), nullable=False)

    # Пояснение переводчику: чем этот «клапан» отличается от соседнего.
    note: Mapped[str | None] = mapped_column(Text)

    # Чем решение обосновано: ссылка на справочник, стандарт или страницу,
    # где термин посмотрели. В рабочих реестрах источник указывают всегда —
    # без него спор о термине через месяц начинается заново. Сюда же ложится
    # адрес, по которому термин нашли в сети, когда каталог пополняется на
    # ходу.
    reference: Mapped[str | None] = mapped_column(Text)

    status: Mapped[GlossaryTermStatus] = mapped_column(
        Enum(GlossaryTermStatus, name="glossary_term_status", native_enum=True),
        nullable=False,
        default=GlossaryTermStatus.PROPOSED,
        index=True,
    )

    # Раскрывать ли при первом употреблении: «маркет-мейкер (market maker,
    # MM)», дальше просто MM. Это правило технического текста, и его можно
    # проверить машинно — но только если оно записано, а не подразумевается.
    expand_on_first_use: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Откуда термин взялся: «manual» — завёл человек, «extracted» — вытащен
    # из самого документа, «import:<источник>» — загружен из внешней базы
    # (Microsoft Terminology, UNTERM, WIPO Pearl, глоссарий заказчика).
    #
    # Колонка заведена до того, как импорт написан, намеренно: без неё
    # загруженную пачку нельзя ни обновить целиком, ни снять, не задев
    # термины, которые правил человек, — а добавлять её потом значит
    # переписывать уже накопленные строки вслепую.
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="manual", index=True)

    kind: Mapped[GlossaryEntryKind] = mapped_column(
        Enum(GlossaryEntryKind, name="glossary_entry_kind", native_enum=True),
        nullable=False,
        default=GlossaryEntryKind.TERM,
        index=True,
    )

    # Значим ли регистр при поиске в тексте. Для обычного термина — нет:
    # «клапан» и «Клапан» это одно и то же. Для аббревиатуры — да, иначе
    # «СИЗ» найдётся в «сиз» и наоборот, а «ИТ» — внутри любого слова.
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Термин, обязательный к употреблению, против рекомендованного. Проверка
    # ведёт себя по-разному: обязательный при отсутствии в переводе помечает
    # сегмент, рекомендованный — нет.
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Из какой загрузки запись. Повторная загрузка переписывает ссылку на
    # себя: термин принадлежит последнему файлу, в котором он был. SET NULL —
    # удалённая запись о загрузке не уносит термины.
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_uploads.id", ondelete="SET NULL"),
        index=True,
    )


class GlossaryUpload(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Запись о загруженном словаре: кто, что и с каким итогом.

    Нужна двум людям. Загрузившему — чтобы видеть историю: какие файлы
    приходили и что из них доехало. Администратору площадки — чтобы
    узнать, что появился новый словарь, и решить, что из него годится в
    общий. Второе возможно только с разрешения пространства, и разрешение
    записывается сюда на момент загрузки: передумавший позже не отзывает
    уже одобренного, а новые загрузки идут по новому решению.
    """

    __tablename__ = "glossary_uploads"

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Как назвал источник тот, кто грузил: имя базы или заказчика.
    origin: Mapped[str] = mapped_column(String(100), nullable=False)

    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)

    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Разрешило ли пространство отдать термины этой загрузки площадке.
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Когда и кто из администраторов площадки посмотрел загрузку. Лента в
    # админке открывается ради непросмотренных.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
