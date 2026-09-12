"""Глоссарий: как это называется у заказчика.

Глоссарий ничего не переводит. Он работает с двух сторон: термины, которые
встретились в сегменте, кладутся в запрос к модели, а потом проверяется, что
модель их употребила. Без этого один и тот же housing станет «корпусом» в
главе 2 и «кожухом» в главе 7, и вычитка обойдётся дороже перевода.

Термины загружаются один раз на весь документ и дальше сопоставляются в
памяти. Запрос к базе на каждый сегмент дал бы тысячи обращений там, где
хватает одного, а словарь заказчика измеряется сотнями строк, а не
миллионами — он помещается в память целиком.

Импорт внешних баз (Microsoft Terminology, UNTERM, WIPO Pearl, глоссарий
заказчика) идёт через поле `source`: загруженная пачка отличима от того,
что правил человек. У каждой загрузки есть своя запись — кто, что и с
каким итогом принёс — и разрешение пространства отдать её термины
площадке.

Общий словарь площадки подмешивается в работу подсказками: термины по
тематике пространства, которых в его словаре нет, уходят модели как
рекомендации — необязательные и неустоявшиеся, чтобы ни один сегмент не
получил замечание из-за чужого решения.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.models.memory import (
    GlossaryEntryKind,
    GlossaryTerm,
    GlossaryTermStatus,
    GlossaryUpload,
)
from app.models.organization import Role
from app.models.project import Project
from app.models.shared import SharedTerm
from app.services.base import TenantService
from app.services.dictionaries import ImportedTerm
from app.services.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
)
from app.services.search import ESCAPE, contains
from app.services.workspace import SETTINGS_ROLES, WorkspaceSettingsService, subject_for

EDITING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

# Метка записи, заведённой человеком. Загруженная пачка её не перезаписывает.
MANUAL = "manual"
# Метка записи, принятой из общего словаря площадки.
PLATFORM = "platform"

# Сколько строк уходит в базу одним оператором. Двадцать тысяч отдельных
# вставок — это минуты вместо секунд.
INSERT_BATCH = 500
LOOKUP_BATCH = 1000

# Сколько причин пропуска показывать. Полный список на десять тысяч строк
# никто не читает, а первых достаточно, чтобы понять, что колонки перепутаны.
MAX_REASONS = 20

# Что разрешено менять правкой. Исходный термин и языковая пара в список не
# входят: смена любого из них — это другая запись, а не правка этой, и
# уникальность в базе построена именно на них.
UPDATABLE_FIELDS = frozenset(
    {
        "target_term",
        "note",
        "reference",
        "mandatory",
        "status",
        "kind",
        "case_sensitive",
        "expand_on_first_use",
    }
)

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
    # Устоялось ли решение по термину. Неустоявшийся уходит модели
    # подсказкой, но не имеет права помечать сегмент ошибкой: иначе редактор
    # получит сотню претензий к переводу там, где спор идёт о самом словаре.
    settled: bool = True
    # Раскрывать ли при первом употреблении: «маркет-мейкер (market maker,
    # MM)», дальше просто MM.
    expand_on_first_use: bool = False


@dataclass(slots=True)
class ImportReport:
    """Чем закончилась загрузка словаря."""

    total: int
    added: int = 0
    updated: int = 0
    skipped: int = 0
    # Причины пропуска, а не одно число: «пропущено 240» ничего не говорит,
    # а «нет перевода» говорит, что колонки перепутаны местами.
    reasons: list[str] = field(default_factory=list)
    # Запись о загрузке — с разрешением, под которым она прошла.
    upload: GlossaryUpload | None = None

    def reason(self, text: str) -> None:
        if len(self.reasons) < MAX_REASONS:
            self.reasons.append(text)


@dataclass(slots=True)
class GlossaryPage:
    total: int
    items: list[GlossaryTerm]


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

    @property
    def terms(self) -> list[Term]:
        return list(self._terms)

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
            if not term.mandatory or not term.settled:
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
            # Снятое в работу не идёт вовсе: дубликат или признанная ошибка
            # не должны ни подсказываться модели, ни проверяться в ответе.
            GlossaryTerm.status != GlossaryTermStatus.RETIRED,
        )

        # Потолок на то, что попадёт в работу. Каждый термин превращается в
        # регулярное выражение и прогоняется по каждому сегменту: двадцать
        # тысяч терминов на книге в десять тысяч сегментов — это двести
        # миллионов поисков за прогон. Загруженная целиком чужая термбаза
        # именно так и выглядит.
        limit = get_settings().glossary_max_active_terms
        rows = list(await self._session.scalars(query.limit(limit + 1)))

        if len(rows) > limit:
            raise ConflictError(
                f"В словаре больше {limit} действующих терминов. Ограничьте его "
                "проектом или снимите лишние: иначе каждый сегмент проверяется "
                "по всей базе."
            )

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
                settled=row.status is GlossaryTermStatus.CONFIRMED,
                expand_on_first_use=row.expand_on_first_use,
            )

        # Общий словарь площадки — подсказками и только там, где своего
        # решения нет: своё слово заказчика всегда важнее чужого. Термин
        # приходит необязательным и неустоявшимся, поэтому модель его
        # видит, а проверка сегмент за него не помечает. В потолок он
        # укладывается вместе со своими.
        for shared in await self._shared(
            source_language=source_language,
            target_language=target_language,
            known=chosen,
            limit=limit - len(rows),
        ):
            chosen[shared.source_term_normalized] = Term(
                source=shared.source_term,
                target=shared.target_term,
                mandatory=False,
                note=shared.note,
                kind=shared.kind,
                case_sensitive=shared.kind
                in (GlossaryEntryKind.ABBREVIATION, GlossaryEntryKind.DO_NOT_TRANSLATE),
                settled=False,
            )

        return Glossary(list(chosen.values()))

    async def _shared(
        self,
        *,
        source_language: str,
        target_language: str,
        known: Mapping[str, Term],
        limit: int,
    ) -> list[SharedTerm]:
        """Термины общего словаря по тематике пространства, которых нет в своём."""
        if limit <= 0:
            return []

        subject = await subject_for(self._session, self.organization_id)
        if subject is None:
            return []

        query = (
            select(SharedTerm)
            .where(
                SharedTerm.subject == subject,
                SharedTerm.source_language == source_language,
                SharedTerm.target_language == target_language,
            )
            .order_by(SharedTerm.source_term_normalized)
            .limit(limit + len(known))
        )

        rows = await self._session.scalars(query)

        return [row for row in rows if row.source_term_normalized not in known][:limit]

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        query: str | None = None,
        kind: GlossaryEntryKind | None = None,
        status: GlossaryTermStatus | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> GlossaryPage:
        """Страница словаря с отбором.

        Общее число считается по тому же отбору отдельным запросом: страница
        показывает двести строк из двух тысяч, а человеку нужно знать, сколько
        всего подходит под его условие.
        """
        statement = self.scoped(GlossaryTerm)

        if project_id is not None:
            statement = statement.where(
                or_(GlossaryTerm.project_id.is_(None), GlossaryTerm.project_id == project_id)
            )

        if query:
            pattern = contains(query)
            statement = statement.where(
                or_(
                    GlossaryTerm.source_term_normalized.ilike(pattern, escape=ESCAPE),
                    GlossaryTerm.target_term.ilike(pattern, escape=ESCAPE),
                )
            )

        if kind is not None:
            statement = statement.where(GlossaryTerm.kind == kind)

        if status is not None:
            statement = statement.where(GlossaryTerm.status == status)

        total = await self._count(statement)
        rows = await self._session.scalars(
            statement.order_by(GlossaryTerm.source_term_normalized).limit(limit).offset(offset)
        )

        return GlossaryPage(total=total, items=list(rows))

    async def _count(self, statement: Select[tuple[GlossaryTerm]]) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )

        return int(counted or 0)

    # Sequence, а не list: в теле класса имя `list` уже занято методом выше,
    # и аннотация `list[...]` разрешилась бы в него.
    async def uploads(self, *, limit: int = 50) -> Sequence[GlossaryUpload]:
        """История загрузок пространства: последние первыми."""
        return list(
            await self._session.scalars(
                self.scoped(GlossaryUpload).order_by(GlossaryUpload.created_at.desc()).limit(limit)
            )
        )

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
        # Заведённое руками считается решённым: человек, набравший перевод,
        # уже договорился с собой. Загруженная пачка приходит с PROPOSED —
        # чужой словарь верен не весь.
        status: GlossaryTermStatus = GlossaryTermStatus.CONFIRMED,
        reference: str | None = None,
        expand_on_first_use: bool = False,
        commit: bool = True,
    ) -> GlossaryTerm:
        """Завести термин либо уточнить существующий.

        `commit=False` нужен вызывающему, который заводит термины пачкой:
        решения по двумстам кандидатам — это одна операция человека, и
        двести отдельных транзакций из неё делать незачем. Тогда границу
        транзакции ставит вызывающий, а здесь достаточно flush — после него
        у объекта уже есть идентификатор, на который можно сослаться.
        """
        self._context.require(*EDITING_ROLES)
        await self._require_project(project_id)

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
            existing.status = status
            existing.reference = reference
            existing.expand_on_first_use = expand_on_first_use
            await self._finish(existing, commit=commit)

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
            status=status,
            reference=reference,
            expand_on_first_use=expand_on_first_use,
        )

        self._session.add(term)
        await self._finish(term, commit=commit)

        return term

    async def _finish(self, term: GlossaryTerm, *, commit: bool) -> None:
        if commit:
            await self._session.commit()
            await self._session.refresh(term)
        else:
            # flush, а не commit: строка уходит в базу и получает
            # идентификатор, но транзакцию закрывает вызывающий.
            await self._session.flush()

    async def _require_project(self, project_id: uuid.UUID | None) -> None:
        """Проект термина обязан быть проектом этой организации.

        Сам термин пишется в свою организацию, но внешний ключ на чужой
        проект связал бы его с чужой сущностью: удаление того проекта
        каскадом унесло бы наши термины, а разница между ошибкой ключа и
        успехом подсказывала бы, существует ли чужой идентификатор.
        """
        if project_id is None:
            return

        exists = await self._session.scalar(
            self.scoped(Project).where(Project.id == project_id).with_only_columns(Project.id)
        )
        if exists is None:
            raise NotFoundError("Проект не найден")

    async def import_terms(
        self,
        terms: Sequence[ImportedTerm],
        *,
        source_language: str,
        target_language: str,
        origin: str,
        filename: str,
        project_id: uuid.UUID | None = None,
        overwrite_manual: bool = False,
        share: bool | None = None,
        unreadable: int = 0,
    ) -> ImportReport:
        """Загрузить пачку записей из внешнего словаря.

        Главное правило: загруженное не затирает ручную работу. Человек,
        поправивший термин, знает про эту книгу больше, чем чужая база на
        двадцать тысяч строк, и молча переписать его правку — это потерять
        работу, о которой никто не узнает. Такие записи пропускаются, а
        `overwrite_manual` включается осознанно.

        Запись идёт одним оператором на пачку, а не строкой за строкой:
        двадцать тысяч отдельных вставок — это минуты вместо секунд.

        `share` — разрешение отдать термины этой загрузки площадке. Не
        передано — берётся то, что стоит в настройках пространства; передано
        и отличается — становится новой настройкой, и на это нужны права
        администратора пространства: это распоряжение чужими данными, а не
        работа с текстом. `unreadable` — строки, которые не разобрал сам
        файл: они входят в итог загрузки, чтобы запись о ней сходилась с
        тем, что видел человек.
        """
        self._context.require(*EDITING_ROLES)
        await self._require_project(project_id)

        limit = get_settings().max_import_terms
        if len(terms) > limit:
            raise InvalidInputError(f"За раз загружается не больше {limit} записей")

        shared = await self._consent(share)

        report = ImportReport(total=len(terms))
        prepared: dict[str, dict[str, Any]] = {}
        # Идентификатор задаётся здесь, а не при записи в базу: термины
        # ссылаются на загрузку, и ссылка нужна до того, как она записана.
        upload = GlossaryUpload(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            uploaded_by_id=self._context.user.id,
            project_id=project_id,
            filename=filename[:255] or "словарь",
            origin=origin,
            source_language=source_language,
            target_language=target_language,
            shared=shared,
        )

        for term in terms:
            row = self._import_row(
                term,
                source_language=source_language,
                target_language=target_language,
                source=f"import:{origin}",
                project_id=project_id,
                upload_id=upload.id,
                report=report,
            )
            if row is not None:
                # Повтор внутри файла — это уточнение ниже по списку, а не
                # ошибка. Побеждает последнее: иначе вставка упала бы на
                # «ON CONFLICT DO UPDATE command cannot affect row a second
                # time», и не загрузилось бы вообще ничего.
                prepared[str(row["source_term_normalized"])] = row

        existing = await self._existing_sources(
            list(prepared),
            source_language=source_language,
            target_language=target_language,
            project_id=project_id,
        )

        writable = []

        for key, row in prepared.items():
            previous = existing.get(key)

            if previous is None:
                report.added += 1
            elif previous == MANUAL and not overwrite_manual:
                report.skipped += 1
                report.reason(f"{row['source_term']}: заведён вручную, не перезаписан")
                continue
            else:
                report.updated += 1

            writable.append(row)

        # Запись о загрузке — до терминов: они ссылаются на неё.
        upload.total = report.total + unreadable
        upload.added = report.added
        upload.updated = report.updated
        upload.skipped = report.skipped + unreadable
        self._session.add(upload)
        await self._session.flush()

        await self._write_imported(
            writable, project_id=project_id, overwrite_manual=overwrite_manual
        )
        await self._session.commit()
        await self._session.refresh(upload)

        report.upload = upload

        return report

    async def _consent(self, share: bool | None) -> bool:
        """Под каким разрешением идёт загрузка."""
        settings = await WorkspaceSettingsService(self._session, self._context).load()
        current = settings is not None and settings.share_glossary

        if share is None or share == current:
            return current

        if self._context.role is not Role.OWNER and self._context.role not in SETTINGS_ROLES:
            raise AccessDeniedError(
                "Разрешение на общий словарь даёт владелец или администратор пространства"
            )

        await WorkspaceSettingsService(self._session, self._context).save(share_glossary=share)

        return share

    def _import_row(
        self,
        term: ImportedTerm,
        *,
        source_language: str,
        target_language: str,
        source: str,
        project_id: uuid.UUID | None,
        upload_id: uuid.UUID,
        report: ImportReport,
    ) -> dict[str, Any] | None:
        normalized = normalize_term(term.source_term)

        if not normalized or not term.target_term.strip():
            report.skipped += 1
            report.reason(f"пустая запись: {term.source_term[:60]}")
            return None

        if term.kind is GlossaryEntryKind.DO_NOT_TRANSLATE and (
            normalize_term(term.target_term) != normalized
        ):
            # Отдельная строка файла не должна ронять загрузку целиком:
            # человек увидит причину и поправит именно её.
            report.skipped += 1
            report.reason(f"{term.source_term}: помечен непереводимым, но перевод отличается")
            return None

        return {
            "id": uuid.uuid4(),
            "organization_id": self.organization_id,
            "project_id": project_id,
            "source_language": source_language,
            "target_language": target_language,
            "source_term": term.source_term.strip(),
            "source_term_normalized": normalized,
            "target_term": term.target_term.strip(),
            "note": term.note,
            "reference": term.reference,
            "mandatory": True,
            "source": source,
            "kind": term.kind,
            "status": term.status,
            "case_sensitive": term.kind
            in (GlossaryEntryKind.ABBREVIATION, GlossaryEntryKind.DO_NOT_TRANSLATE),
            "expand_on_first_use": term.expand_on_first_use,
            "upload_id": upload_id,
        }

    async def _existing_sources(
        self,
        keys: Sequence[str],
        *,
        source_language: str,
        target_language: str,
        project_id: uuid.UUID | None,
    ) -> "dict[str, str]":
        """Что из загружаемого уже есть в словаре и откуда оно там взялось."""
        found: dict[str, str] = {}

        for start in range(0, len(keys), LOOKUP_BATCH):
            query = self.scoped(GlossaryTerm).where(
                GlossaryTerm.source_language == source_language,
                GlossaryTerm.target_language == target_language,
                GlossaryTerm.project_id.is_(None)
                if project_id is None
                else GlossaryTerm.project_id == project_id,
                GlossaryTerm.source_term_normalized.in_(keys[start : start + LOOKUP_BATCH]),
            )

            for row in await self._session.scalars(query):
                found[row.source_term_normalized] = row.source

        return found

    async def _write_imported(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        project_id: uuid.UUID | None,
        overwrite_manual: bool,
    ) -> None:
        if not rows:
            return

        # Уникальность в базе держат два частичных индекса — для терминов
        # проекта и для общих. Цель конфликта указывается тем же условием,
        # иначе Postgres не находит индекс и отвергает запрос целиком.
        if project_id is None:
            elements = [
                "organization_id",
                "source_language",
                "target_language",
                "source_term_normalized",
            ]
            index_where = text("project_id IS NULL")
        else:
            elements = [
                "organization_id",
                "project_id",
                "source_language",
                "target_language",
                "source_term_normalized",
            ]
            index_where = text("project_id IS NOT NULL")

        for start in range(0, len(rows), INSERT_BATCH):
            statement = insert(GlossaryTerm).values(rows[start : start + INSERT_BATCH])
            updates = {
                name: statement.excluded[name]
                for name in (
                    "source_term",
                    "target_term",
                    "note",
                    "reference",
                    "source",
                    "kind",
                    "status",
                    "case_sensitive",
                    "expand_on_first_use",
                    "upload_id",
                )
            }

            statement = statement.on_conflict_do_update(
                index_elements=elements,
                index_where=index_where,
                set_=updates,
                # Тот же запрет, что и выше, но на стороне базы: между
                # проверкой и записью термин мог поправить человек.
                where=None if overwrite_manual else GlossaryTerm.source != MANUAL,
            )

            await self._session.execute(statement)

    async def update(self, term_id: uuid.UUID, changes: Mapping[str, Any]) -> GlossaryTerm:
        """Правка записи — то, чем живёт перепроверка словаря.

        Второй проход по словарю не заводит термины заново, а меняет
        решения: подтверждает, исправляет перевод, снимает дубликат. Метод
        принимает только то, что клиент действительно прислал, — иначе
        правка одного поля затирала бы остальные значениями по умолчанию.
        """
        self._context.require(*EDITING_ROLES)

        unknown = set(changes) - UPDATABLE_FIELDS
        if unknown:
            raise InvalidInputError("Нельзя менять поля: " + ", ".join(sorted(unknown)))

        term = await self._session.scalar(
            self.scoped(GlossaryTerm).where(GlossaryTerm.id == term_id)
        )
        if term is None:
            raise NotFoundError("Термин не найден")

        for name, value in changes.items():
            setattr(term, name, value)

        if not term.target_term.strip():
            raise InvalidInputError("Перевод термина не может быть пустым")

        if term.kind is GlossaryEntryKind.DO_NOT_TRANSLATE and normalize_term(
            term.target_term
        ) != normalize_term(term.source_term):
            raise InvalidInputError(
                "Непереводимая запись обязана совпадать с исходной: "
                "смысл вида в том, что строка остаётся как есть"
            )

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
