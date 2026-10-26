"""Гейт терминологии: готова ли глава к переводу с точки зрения терминов.

Прежде перевод запрещался только при нерешённых кандидатах, и прохода,
который ни разу не запускали, это не касалось: нет кандидатов — нет и
запрета. Здесь условие обратное и явное. Глава открыта для перевода,
только если для неё действует утверждённая версия глоссария, собранная по
нынешнему тексту главы, и по главе не осталось нерешённых кандидатов.
Пустая версия — тоже решение, но только записанное: «терминов нет» с
основанием, а не пропущенный этап.

Ответ машиночитаемый: у каждой причины свой код, по которому её узнаёт и
интерфейс, и автоматический режим, — и человеческая фраза для экрана.
Помимо причин, которые держат главу, есть предупреждения: они не держат,
но о них нужно знать — например, что в рабочем словаре есть правки,
которые ещё не утверждены.

Те же проверки решают, можно ли утвердить черновик версии: утверждают
только то, что собрано по нынешнему тексту и ничего не оставляет
нерешённым.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.models.book import BookEdition
from app.models.chapter import BoundaryStatus, Chapter
from app.models.glossary_version import GlossaryVersion, GlossaryVersionStatus, GlossaryVersionTerm
from app.models.master import ChapterMaster
from app.models.memory import GlossaryTermStatus
from app.models.terminology import TerminologyPass
from app.services.base import TenantService
from app.services.errors import ConflictError, NotFoundError
from app.services.glossary import GlossaryService
from app.services.term_impact import checksum, entry_of
from app.services.terminology import TerminologyService

# Решение по обязательному термину под вопросом — утверждать версию с ним
# нельзя: это значит утвердить спор, а не его итог.
UNSETTLED = (GlossaryTermStatus.NEEDS_REVIEW, GlossaryTermStatus.NEEDS_UNIFICATION)

# Сколько терминов назвать поимённо в причине: дальше — числом.
NAMED_TERMS = 5


@dataclass(frozen=True, slots=True)
class GateItem:
    """Одна причина или предупреждение: код для машины, фраза для человека."""

    code: str
    message: str
    chapter_id: uuid.UUID | None = None
    count: int | None = None


@dataclass(slots=True)
class ChapterState:
    """Что известно о терминологии главы прямо сейчас."""

    chapter: Chapter
    master: ChapterMaster | None
    # Проход по нынешнему тексту главы — по её текущему мастеру.
    current_pass: TerminologyPass | None
    undecided: int

    @property
    def collected(self) -> bool:
        """Кандидаты собраны, и собраны по нынешнему тексту главы."""
        return self.current_pass is not None

    @property
    def name(self) -> str:
        return self.chapter.code or f"глава {self.chapter.ordinal}"


@dataclass(slots=True)
class Gate:
    """Гейт главы: какая версия действует, и что мешает переводу."""

    state: ChapterState
    # Действующая утверждённая версия — по ней будут переводить.
    version: GlossaryVersion | None
    # Черновик, который ждёт утверждения и, будучи утверждён, станет
    # действующим для главы.
    draft: GlossaryVersion | None
    blockers: list[GateItem] = field(default_factory=list)
    warnings: list[GateItem] = field(default_factory=list)

    @property
    def open(self) -> bool:
        return not self.blockers


@dataclass(slots=True)
class _Versions:
    """Действующие версии книги и черновики — одним запросом на книгу."""

    approved_book: GlossaryVersion | None = None
    approved_chapters: dict[uuid.UUID, GlossaryVersion] = field(default_factory=dict)
    draft_book: GlossaryVersion | None = None
    draft_chapters: dict[uuid.UUID, GlossaryVersion] = field(default_factory=dict)

    def effective(self, chapter_id: uuid.UUID | None) -> GlossaryVersion | None:
        """Версия, по которой переводят главу: своя, иначе книжная."""
        if chapter_id is not None and chapter_id in self.approved_chapters:
            return self.approved_chapters[chapter_id]

        return self.approved_book

    def draft(self, chapter_id: uuid.UUID) -> GlossaryVersion | None:
        return self.draft_chapters.get(chapter_id) or self.draft_book


class TerminologyGate(TenantService):
    async def check(self, chapter_id: uuid.UUID) -> Gate:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))

        if chapter is None:
            raise NotFoundError("Глава не найдена")

        book = await self._book(chapter.book_id)

        return (await self._evaluate(book, [chapter]))[0]

    async def book(self, book_id: uuid.UUID) -> list[Gate]:
        """Гейты всех глав книги по порядку."""
        book = await self._book(book_id)

        return await self._evaluate(book, await self.chapters(book.id))

    async def chapters(self, book_id: uuid.UUID) -> list[Chapter]:
        return list(
            await self._session.scalars(
                self.scoped(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.ordinal)
            )
        )

    async def states(self, chapters: Sequence[Chapter]) -> list[ChapterState]:
        """Мастер, проход по нему и нерешённые кандидаты каждой главы."""
        ids = [chapter.id for chapter in chapters]
        masters = await self.current_masters(ids)
        terminology = TerminologyService(self._session, self._context)
        passes = await terminology.passes_over([master.id for master in masters.values()])
        undecided = await terminology.undecided_by_chapter(ids)
        states = []

        for chapter in chapters:
            master = masters.get(chapter.id)
            states.append(
                ChapterState(
                    chapter=chapter,
                    master=master,
                    current_pass=None if master is None else passes.get(master.id),
                    undecided=undecided.get(chapter.id, 0),
                )
            )

        return states

    async def current_masters(
        self, chapter_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, ChapterMaster]:
        """Текущая — последняя — версия мастера каждой главы."""
        if not chapter_ids:
            return {}

        rows = await self._session.scalars(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id.in_(chapter_ids))
            .order_by(ChapterMaster.chapter_id, ChapterMaster.version.desc())
            .distinct(ChapterMaster.chapter_id)
        )

        return {row.chapter_id: row for row in rows}

    async def effective(
        self, book_id: uuid.UUID, chapter_id: uuid.UUID | None
    ) -> GlossaryVersion | None:
        """Действующая версия для области: главы — своя или книжная, книги — книжная."""
        return (await self._versions(book_id)).effective(chapter_id)

    async def working_checksum(self, book: BookEdition) -> str:
        """Сумма рабочего словаря книги — в той же записи, что у снимка версии."""
        rows = await GlossaryService(self._session, self._context).own_terms(
            project_id=book.project_id,
            source_language=book.source_language,
            target_language=book.target_language,
        )

        return checksum(entry_of(row) for row in rows)

    async def approval_blockers(self, version: GlossaryVersion) -> list[GateItem]:
        """Что мешает утвердить черновик версии."""
        if version.chapter_id is None:
            chapters = await self.chapters(version.book_id)
        else:
            chapter = await self._session.scalar(
                self.scoped(Chapter).where(Chapter.id == version.chapter_id)
            )
            chapters = [] if chapter is None else [chapter]

        states = await self.states(chapters)
        basis = {item["chapter_id"]: item["master_id"] for item in version.basis}
        blockers = []

        # Главы разделили или объединили после сборки: черновик описывает
        # другую книгу, и решение о ней ничего не говорит о нынешней.
        if {str(state.chapter.id) for state in states} != set(basis):
            blockers.append(
                GateItem(
                    "basis_outdated",
                    "Состав глав изменился после сборки черновика — соберите его заново",
                )
            )

        for state in states:
            blockers.extend(self._chapter_blockers(state))

            current = None if state.master is None else str(state.master.id)
            if str(state.chapter.id) in basis and basis[str(state.chapter.id)] != current:
                blockers.append(
                    GateItem(
                        "basis_outdated",
                        f"У главы {state.name} новая версия мастера после сборки черновика "
                        "— соберите кандидаты и черновик заново",
                        chapter_id=state.chapter.id,
                    )
                )

        effective = (await self._versions(version.book_id)).effective(version.chapter_id)
        base_now = None if effective is None else effective.id

        # Список отличий и затронутых блоков считался против прежней
        # действующей версии; если с тех пор утвердили другую, он неверен.
        if base_now != version.base_id:
            label = "другая версия" if effective is None else effective.label
            blockers.append(
                GateItem(
                    "base_changed",
                    f"После сборки черновика утверждена {label} — соберите черновик заново",
                )
            )

        unsettled = list(
            await self._session.scalars(
                self.scoped(GlossaryVersionTerm)
                .where(
                    GlossaryVersionTerm.version_id == version.id,
                    GlossaryVersionTerm.mandatory.is_(True),
                    GlossaryVersionTerm.status.in_(UNSETTLED),
                )
                .order_by(GlossaryVersionTerm.source_term_normalized)
            )
        )

        if unsettled:
            named = ", ".join(term.source_term for term in unsettled[:NAMED_TERMS])
            rest = len(unsettled) - NAMED_TERMS
            blockers.append(
                GateItem(
                    "terms_unsettled",
                    f"Решение под вопросом у обязательных терминов: {named}"
                    + (f" и ещё {rest}" if rest > 0 else ""),
                    count=len(unsettled),
                )
            )

        return blockers

    async def _evaluate(self, book: BookEdition, chapters: Sequence[Chapter]) -> list[Gate]:
        states = await self.states(chapters)
        versions = await self._versions(book.id)

        # Рабочий словарь сверяется с действующей версией один раз на книгу:
        # он один у всех её глав.
        working: str | None = None
        unreadable: str | None = None

        try:
            working = await self.working_checksum(book)
        except ConflictError as error:
            unreadable = str(error)

        gates = []

        for state in states:
            version = versions.effective(state.chapter.id)
            gate = Gate(state=state, version=version, draft=versions.draft(state.chapter.id))
            gate.blockers.extend(self._chapter_blockers(state))

            if version is None:
                pending = (
                    "" if gate.draft is None else f" — черновик {gate.draft.label} ждёт решения"
                )
                gate.blockers.append(
                    GateItem(
                        "no_approved_version",
                        f"Нет утверждённой версии глоссария{pending}",
                        chapter_id=state.chapter.id,
                    )
                )
            else:
                gate.blockers.extend(self._coverage(state, version))

                if unreadable is not None:
                    gate.warnings.append(GateItem("glossary_unreadable", unreadable))
                elif working != version.checksum:
                    gate.warnings.append(
                        GateItem(
                            "glossary_changed",
                            f"В рабочем словаре есть правки после {version.label} — они не "
                            "действуют, пока не утверждена новая версия",
                        )
                    )

            gates.append(gate)

        return gates

    @staticmethod
    def _chapter_blockers(state: ChapterState) -> list[GateItem]:
        """Причины, которые держат главу при любой версии глоссария."""
        chapter_id = state.chapter.id

        if state.chapter.boundary_status is BoundaryStatus.DRAFT:
            return [
                GateItem(
                    "boundaries_draft",
                    f"Границы главы {state.name} не утверждены",
                    chapter_id=chapter_id,
                )
            ]

        if state.master is None:
            return [
                GateItem(
                    "master_missing",
                    f"У главы {state.name} нет мастера — сначала извлеките её текст",
                    chapter_id=chapter_id,
                )
            ]

        blockers = []

        if not state.collected:
            blockers.append(
                GateItem(
                    "terms_not_collected",
                    f"По нынешнему тексту главы {state.name} не собраны кандидаты в термины",
                    chapter_id=chapter_id,
                )
            )

        if state.undecided:
            blockers.append(
                GateItem(
                    "candidates_undecided",
                    f"В главе {state.name} кандидатов без решения: {state.undecided}",
                    chapter_id=chapter_id,
                    count=state.undecided,
                )
            )

        return blockers

    @staticmethod
    def _coverage(state: ChapterState, version: GlossaryVersion) -> list[GateItem]:
        """Покрывает ли действующая версия нынешний текст главы."""
        if state.master is None:
            return []

        basis = {item["chapter_id"]: item["master_id"] for item in version.basis}
        key = str(state.chapter.id)

        if key not in basis:
            return [
                GateItem(
                    "not_covered",
                    f"Глава {state.name} появилась после утверждения {version.label} — "
                    "соберите кандидаты и новую версию",
                    chapter_id=state.chapter.id,
                )
            ]

        if basis[key] != str(state.master.id):
            return [
                GateItem(
                    "master_changed",
                    f"{version.label} утверждена по прежней версии мастера главы {state.name} — "
                    "соберите кандидаты и новую версию",
                    chapter_id=state.chapter.id,
                )
            ]

        return []

    async def _versions(self, book_id: uuid.UUID) -> _Versions:
        rows = await self._session.scalars(
            self.scoped(GlossaryVersion).where(
                GlossaryVersion.book_id == book_id,
                GlossaryVersion.status.in_(
                    (GlossaryVersionStatus.APPROVED, GlossaryVersionStatus.DRAFT)
                ),
            )
        )
        found = _Versions()

        for row in rows:
            approved = row.status is GlossaryVersionStatus.APPROVED

            if row.chapter_id is None:
                if approved:
                    found.approved_book = row
                else:
                    found.draft_book = row
            elif approved:
                found.approved_chapters[row.chapter_id] = row
            else:
                found.draft_chapters[row.chapter_id] = row

        return found

    async def _book(self, book_id: uuid.UUID) -> BookEdition:
        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))

        if book is None:
            raise NotFoundError("Книга не найдена")

        return book
