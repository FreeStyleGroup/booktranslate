"""Предложение глав по основному источнику книги.

Сервис предлагает, человек утверждает. Предложение строится в два шага.

Сначала поток блоков режется на разделы: новый раздел начинается с
каждого заголовка. Раздел — наименьшая единица, по которой глава потом
делится и сливается: делить главу посреди абзаца незачем, а посреди
раздела — значит разорвать подзаголовок и его текст.

Затем разделы группируются в главы. Глава начинается с заголовка
верхнего уровня — того, что встречается в книге хотя бы дважды: один
заголовок над всеми обычно название книги, а не глава. Если заголовков
нет вовсе, якорями служат файлы EPUB или страницы PDF — это те
«heading / path / page anchors», о которых говорит процесс.

Обе функции чистые: на входе блоки или разделы, на выходе структура. Так
их можно проверить на настоящих книгах без базы и без хранилища.
"""

import asyncio
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import BoundaryStatus, Chapter, ChapterOrigin
from app.models.document import Document, SourceRole
from app.models.segment import SegmentKind
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.books import MANAGING_ROLES, BookService
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError
from app.services.parsers import PARSER_VERSION, ParsedBlock, ParsingError, parser_for
from app.services.source_files import local_copy
from app.services.storage import ObjectStorage

# Что из места блока показывать человеку: файл EPUB, страницу PDF, строку
# Markdown. Номер блока сюда не входит — он хранится отдельно и человеку
# ничего не говорит.
LOCATOR_KEYS = ("href", "page", "line")

# Предел длины названия главы — от колонки. Заголовок длиннее — почти
# всегда склеенный абзац, и хранить его целиком в названии незачем.
TITLE_MAX = 500


@dataclass(frozen=True, slots=True)
class Section:
    """Подряд идущие блоки от заголовка до следующего заголовка.

    `level` пуст у раздела без заголовка — так выглядит начало книги до
    первого заголовка и страница PDF, где заголовков нет вовсе.
    """

    start: int
    end: int
    level: int | None
    title: str | None
    locator: dict[str, Any]
    kinds: dict[str, int] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "level": self.level,
            "title": self.title,
            "locator": self.locator,
            "kinds": self.kinds,
        }


@dataclass(frozen=True, slots=True)
class Proposal:
    """Предложенная глава: диапазон блоков и разделы внутри него."""

    title: str | None
    sections: list[Section]
    origin: ChapterOrigin

    @property
    def start(self) -> int:
        return self.sections[0].start

    @property
    def end(self) -> int:
        return self.sections[-1].end

    @property
    def locator(self) -> dict[str, Any]:
        return self.sections[0].locator


def sections_of(blocks: Sequence[ParsedBlock]) -> list[Section]:
    """Нарезать поток блоков на разделы.

    Номер блока — его место в потоке разбора: тот же номер получит блок и
    при извлечении мастера, если файл и версия разбора те же.
    """
    if not blocks:
        return []

    if any(block.kind is SegmentKind.HEADING for block in blocks):
        starts = [
            index
            for index, block in enumerate(blocks)
            if index == 0 or block.kind is SegmentKind.HEADING
        ]
    else:
        # Заголовков нет: якорем служит смена файла EPUB или страницы PDF.
        # У простого текста нет ни того, ни другого — он один раздел.
        starts = [
            index
            for index, block in enumerate(blocks)
            if index == 0 or _anchor(block) != _anchor(blocks[index - 1])
        ]

    bounds = [*starts, len(blocks)]

    return [_section(blocks, start, end) for start, end in zip(bounds, bounds[1:], strict=False)]


def propose(sections: Sequence[Section]) -> list[Proposal]:
    """Сгруппировать разделы в главы."""
    if not sections:
        return []

    levels = [section.level for section in sections if section.level is not None]

    if not levels:
        return _without_headings(sections)

    top = chapter_level(levels)
    groups: list[list[Section]] = []

    for section in sections:
        opens = section.level is not None and section.level <= top

        if not groups or opens:
            groups.append([section])
        else:
            groups[-1].append(section)

    return [
        Proposal(title=_title_of(group, top), sections=group, origin=ChapterOrigin.HEADING)
        for group in groups
    ]


def chapter_level(levels: Iterable[int]) -> int:
    """Уровень заголовков, с которых начинаются главы.

    Самый верхний из встречающихся хотя бы дважды. Один заголовок над всеми
    — это название книги или части, а не глава: сделай его уровнем глав, и
    вся книга станет одной главой. Если повторов нет вовсе, глава одна, и
    её начинает самый верхний заголовок.
    """
    counts = Counter(levels)
    repeated = [level for level, count in counts.items() if count >= 2]

    return min(repeated) if repeated else min(counts)


def _without_headings(sections: Sequence[Section]) -> list[Proposal]:
    """Глав по заголовкам не выделить — по чему тогда.

    Файлы EPUB — это главы, как их разрезал издатель, и каждый становится
    главой. Страницы PDF главами не бывают: глава одна, а разделы в ней —
    страницы, по которым человек её разделит. Остальное — документ целиком.
    """
    if any("href" in section.locator for section in sections):
        return [
            Proposal(title=None, sections=[section], origin=ChapterOrigin.PATH)
            for section in sections
        ]

    paged = any("page" in section.locator for section in sections)
    origin = ChapterOrigin.PAGE if paged else ChapterOrigin.WHOLE

    return [Proposal(title=None, sections=list(sections), origin=origin)]


def _section(blocks: Sequence[ParsedBlock], start: int, end: int) -> Section:
    first = blocks[start]
    heading = first.kind is SegmentKind.HEADING
    level = first.location.get("level") if heading else None

    return Section(
        start=start,
        end=end,
        # Заголовок без уровня — первого: так его покажет и сборщик.
        level=(level if isinstance(level, int) else 1) if heading else None,
        title=" ".join(first.text.split())[:TITLE_MAX] if heading else None,
        locator={key: first.location[key] for key in LOCATOR_KEYS if key in first.location},
        kinds=dict(Counter(block.kind.value for block in blocks[start:end])),
    )


def _anchor(block: ParsedBlock) -> Any:
    return block.location.get("href", block.location.get("page"))


def _title_of(group: Sequence[Section], top: int) -> str | None:
    """Название главы — её заголовок верхнего уровня, иначе первый любой."""
    for section in group:
        if section.level is not None and section.level <= top:
            return section.title

    return next((section.title for section in group if section.title), None)


class ChapterDetectionService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def propose(self, book_id: uuid.UUID) -> list[Chapter]:
        """Предложить главы по основному источнику — заменив прежнее предложение.

        Заново предлагать можно, пока ни одна глава не утверждалась: после
        утверждения у глав есть коды, и выбросить их значит выбросить то,
        на что уже могли сослаться. Утверждённую структуру правят
        разделением и объединением.
        """
        self._context.require(*MANAGING_ROLES)

        books = BookService(self._session, self._context)
        book = await books.lock(book_id)

        numbered = await self._session.scalar(
            self.scoped(Chapter).where(Chapter.book_id == book.id, Chapter.number.is_not(None))
        )
        if numbered is not None:
            raise ConflictError(
                "Границы глав уже утверждались. Меняйте их разделением и объединением "
                "глав, а не новым предложением"
            )

        source = await self._session.scalar(
            self.scoped(Document).where(
                Document.book_id == book.id, Document.source_role == SourceRole.PRIMARY_TEXT
            )
        )
        if source is None:
            raise ConflictError("Сначала назначьте книге основной источник текста")

        blocks = await self._blocks(source)
        proposals = propose(sections_of(blocks))

        if not proposals:
            raise InvalidInputError("В основном источнике не нашлось текста")

        await self._session.execute(delete(Chapter).where(Chapter.book_id == book.id))

        chapters = [
            Chapter(
                organization_id=self.organization_id,
                book_id=book.id,
                source_document_id=source.id,
                ordinal=ordinal,
                title=proposal.title,
                source_start=proposal.start,
                source_end=proposal.end,
                parser_version=PARSER_VERSION,
                locator=proposal.locator,
                sections=[section.as_json() for section in proposal.sections],
                origin=proposal.origin,
                boundary_status=BoundaryStatus.DRAFT,
                boundary_version=1,
            )
            for ordinal, proposal in enumerate(proposals, start=1)
        ]
        self._session.add_all(chapters)

        AuditService(self._session, self._context).record(
            kind="chapters.proposed",
            subject_type="book_edition",
            subject_id=book.id,
            payload={
                "document_id": str(source.id),
                "parser_version": PARSER_VERSION,
                "chapters": len(chapters),
                "origin": proposals[0].origin.name,
            },
        )

        await self._session.commit()

        return list(
            await self._session.scalars(
                self.scoped(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)
            )
        )

    async def _blocks(self, document: Document) -> list[ParsedBlock]:
        parser = parser_for(document.source_format)

        if parser is None:
            raise InvalidInputError(
                f"Формат {document.source_format.value} пока не разбирается — "
                "главы по нему не предложить"
            )

        async with local_copy(self._storage, document.storage_key) as path:
            try:
                # Разбор целиком и в отдельном потоке: это блокирующая
                # работа с диском, а предложению нужен весь поток блоков —
                # уровень глав виден только по всей книге.
                return await asyncio.to_thread(lambda: list(parser.parse(path)))
            except ParsingError as error:
                raise InvalidInputError(str(error)) from error
