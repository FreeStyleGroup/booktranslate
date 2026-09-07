"""Глоссарий: как это называется у заказчика.

Глоссарий ничего не переводит. Он работает с двух сторон: термины, которые
встретились в сегменте, кладутся в запрос к модели, а потом проверяется, что
модель их употребила. Без этого один и тот же housing станет «корпусом» в
главе 2 и «кожухом» в главе 7, и вычитка обойдётся дороже перевода.

Термины загружаются один раз на весь документ и дальше сопоставляются в
памяти. Запрос к базе на каждый сегмент дал бы тысячи обращений там, где
хватает одного, а словарь заказчика измеряется сотнями строк, а не
миллионами — он помещается в память целиком.

Сюда же будет подключаться импорт внешних баз (Microsoft Terminology,
UNTERM, WIPO Pearl, глоссарий заказчика): у термина есть поле `source`,
и загруженная пачка отличима от того, что правил человек.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import or_

from app.models.memory import GlossaryEntryKind, GlossaryTerm
from app.models.organization import Role
from app.services.base import TenantService
from app.services.errors import InvalidInputError, NotFoundError

EDITING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

_WHITESPACE = re.compile(r"\s+")


def normalize_term(term: str) -> str:
    return _WHITESPACE.sub(" ", term).strip().casefold()


@dataclass(frozen=True, slots=True)
class Term:
    source: str
    target: str
    mandatory: bool
    note: str | None
    kind: GlossaryEntryKind = GlossaryEntryKind.TERM
    # Регистр значим у аббревиатур: «ИТ» без этого нашлось бы внутри любого
    # слова, а «СИЗ» совпало бы с «сиз».
    case_sensitive: bool = False


class Glossary:
    """Термины проекта, готовые к сопоставлению с текстом.

    Сопоставление идёт по границам слов: без них «ток» нашёлся бы внутри
    «поток», а «air» — внутри «repair», и в запрос к модели поехали бы
    требования, которых в тексте нет.
    """

    def __init__(self, terms: list[Term]) -> None:
        # Длинные термины впереди: если есть и «клапан», и «обратный клапан»,
        # в подсказку должен попасть более точный.
        self._terms = sorted(terms, key=lambda term: len(term.source), reverse=True)
        self._patterns = [
            (
                term,
                re.compile(
                    rf"(?<!\w){re.escape(term.source)}(?!\w)",
                    0 if term.case_sensitive else re.IGNORECASE,
                ),
            )
            for term in self._terms
        ]

    def __len__(self) -> int:
        return len(self._terms)

    def match(self, text: str) -> list[Term]:
        """Термины, встретившиеся в тексте."""
        return [term for term, pattern in self._patterns if pattern.search(text)]

    def missing_in(self, source_text: str, target_text: str) -> list[Term]:
        """Обязательные термины, которые есть в исходнике, но не в переводе.

        Проверка нарочно грубая: ищется вхождение целевого термина как
        подстроки, без учёта падежа. Русский флективный, и «клапана» —
        это тот же «клапан»; требовать точную форму значило бы помечать
        правильные переводы. Обратная ошибка (термин переведён падежом,
        которого нет в словаре) остаётся, и это осознанный компромисс:
        ложная тревога дешевле пропущенного расхождения.
        """
        missing = []

        for term in self.match(source_text):
            if not term.mandatory:
                continue

            # Непереводимое и аббревиатуры сверяются дословно, с регистром:
            # «USB» превратившийся в «Usb» — это уже ошибка, а не падежная
            # форма. Обычный термин сверяется без регистра и без окончания.
            if term.case_sensitive or term.kind is GlossaryEntryKind.DO_NOT_TRANSLATE:
                found = term.target in target_text
            else:
                found = normalize_term(term.target) in normalize_term(target_text)

            if not found:
                missing.append(term)

        return missing


class GlossaryService(TenantService):
    async def load(
        self, *, project_id: uuid.UUID | None, source_language: str, target_language: str
    ) -> Glossary:
        """Собрать глоссарий проекта: его термины плюс общие для организации."""
        query = self.scoped(GlossaryTerm).where(
            GlossaryTerm.source_language == source_language,
            GlossaryTerm.target_language == target_language,
            or_(GlossaryTerm.project_id.is_(None), GlossaryTerm.project_id == project_id),
        )

        rows = list(await self._session.scalars(query))

        # Термин проекта важнее общего для организации: заказчик уточняет
        # словарь бюро под себя, и его вариант должен вытеснять, а не
        # соседствовать. Сортировка ставит общие первыми, чтобы проектные
        # затирали их в словаре.
        rows.sort(key=lambda row: row.project_id is not None)

        chosen: dict[str, Term] = {}
        for row in rows:
            chosen[row.source_term_normalized] = Term(
                source=row.source_term,
                target=row.target_term,
                mandatory=row.mandatory,
                note=row.note,
                kind=row.kind,
                case_sensitive=row.case_sensitive,
            )

        return Glossary(list(chosen.values()))

    async def list(
        self, *, project_id: uuid.UUID | None = None, limit: int = 200, offset: int = 0
    ) -> list[GlossaryTerm]:
        query = self.scoped(GlossaryTerm)

        if project_id is not None:
            query = query.where(
                or_(GlossaryTerm.project_id.is_(None), GlossaryTerm.project_id == project_id)
            )

        query = query.order_by(GlossaryTerm.source_term_normalized).limit(limit).offset(offset)

        return list(await self._session.scalars(query))

    async def add(
        self,
        *,
        source_term: str,
        target_term: str,
        source_language: str,
        target_language: str,
        project_id: uuid.UUID | None = None,
        note: str | None = None,
        mandatory: bool = True,
        source: str = "manual",
        kind: GlossaryEntryKind = GlossaryEntryKind.TERM,
        case_sensitive: bool | None = None,
    ) -> GlossaryTerm:
        self._context.require(*EDITING_ROLES)

        normalized = normalize_term(source_term)
        if not normalized or not target_term.strip():
            raise InvalidInputError("Термин и его перевод не могут быть пустыми")

        if kind is GlossaryEntryKind.DO_NOT_TRANSLATE and normalize_term(target_term) != normalized:
            raise InvalidInputError(
                "Непереводимая запись обязана совпадать с исходной: "
                "смысл вида в том, что строка остаётся как есть"
            )

        # У аббревиатур регистр значим по умолчанию, у обычных терминов — нет.
        # Явно переданное значение важнее умолчания вида.
        if case_sensitive is None:
            case_sensitive = kind in (
                GlossaryEntryKind.ABBREVIATION,
                GlossaryEntryKind.DO_NOT_TRANSLATE,
            )

        existing = await self._session.scalar(
            self.scoped(GlossaryTerm).where(
                GlossaryTerm.source_language == source_language,
                GlossaryTerm.target_language == target_language,
                GlossaryTerm.source_term_normalized == normalized,
                GlossaryTerm.project_id.is_(None)
                if project_id is None
                else GlossaryTerm.project_id == project_id,
            )
        )

        # Повторное добавление того же термина — это правка, а не ошибка:
        # человек уточняет перевод, а не заводит второй такой же.
        if existing is not None:
            existing.target_term = target_term.strip()
            existing.note = note
            existing.mandatory = mandatory
            existing.source = source
            existing.kind = kind
            existing.case_sensitive = case_sensitive
            await self._session.commit()
            await self._session.refresh(existing)

            return existing

        term = GlossaryTerm(
            organization_id=self.organization_id,
            project_id=project_id,
            source_language=source_language,
            target_language=target_language,
            source_term=source_term.strip(),
            source_term_normalized=normalized,
            target_term=target_term.strip(),
            note=note,
            mandatory=mandatory,
            source=source,
            kind=kind,
            case_sensitive=case_sensitive,
        )

        self._session.add(term)
        await self._session.commit()
        await self._session.refresh(term)

        return term

    async def delete(self, term_id: uuid.UUID) -> None:
        self._context.require(*EDITING_ROLES)

        term = await self._session.scalar(
            self.scoped(GlossaryTerm).where(GlossaryTerm.id == term_id)
        )
        if term is None:
            raise NotFoundError("Термин не найден")

        await self._session.delete(term)
        await self._session.commit()
