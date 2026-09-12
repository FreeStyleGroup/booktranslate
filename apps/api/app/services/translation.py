"""Перевод сегментов.

Цель — перевод, который можно отдать в печать, а не черновик подешевле.
Это решение (`docs/DECISIONS.md`): дешёвый прогон с последующей вычиткой
в техническом тексте не работает, потому что ошибки в нём терминологические
и видит их только тот, кто читал исходник. Править такое дороже, чем
переводить заново.

Отсюда весь порядок шагов: к моменту, когда сегмент уходит в модель, всё,
что можно было решить заранее, уже решено.

1. **Терминология решена до перевода.** Пока по документу остались
   нерешённые кандидаты, перевод не начинается: слово, отданное модели на
   усмотрение, в сорока сегментах будет названо по-разному.
2. **Одинаковые сегменты собираются вместе.** Не ради экономии, а ради
   того, чтобы повторяющееся предупреждение звучало в книге одинаково;
   то, что за него платят один раз, — приятное следствие.
3. **Память переводов.** То же самое между документами: вторая книга серии
   обязана называть вещи так же, как первая.
4. **Модель получает термины, встретившиеся в этом сегменте** — как
   ограничение, а не как справочный материал, — и соседние сегменты с
   заголовком раздела: без них «он», «указанный выше» и опущенное
   подлежащее переводятся наугад.
5. **Проверки на выходе.** Числа, подстановки, употребление терминов,
   раскрытие аббревиатуры при первом употреблении. Всё, что не сошлось,
   помечает сегмент и уходит к человеку.

Результат возвращается в память, поэтому следующий документ переводится
не только дешевле, но и согласованно с предыдущим.

**Книга переводится порциями, а не одним запросом.** Обратный прокси
режет соединение через четверть часа, и один вызов на шесть тысяч
сегментов до ответа не доживает. Поэтому вызов берёт `limit`
непереведённых сегментов, отвечает, сколько осталось, и клиент зовёт его,
пока остаток не станет нулём. Каждая пачка фиксируется в базе отдельно —
сорвавшийся на десятой пачке прогон оставляет девять переведённых и
оплаченных, а не откатывает всё.

**Прерванный прогон не запирает документ.** Отметка «переводится» — это
условие в базе, и упавший процесс снять её не успевает. Два выхода: при
старте приложения все такие документы возвращаются в состояние по данным
(`recover_interrupted`), а без перезапуска документ, не подававший
признаков жизни дольше порога, разрешено взять повторно с `force=true`.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.organization import Role
from app.models.project import Project
from app.models.segment import Segment, SegmentKind, SegmentStatus
from app.services import checks
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.glossary import Glossary, GlossaryService
from app.services.memory import TranslationMemory, fingerprint
from app.services.providers import (
    EMPTY_CONTEXT,
    Neighbourhood,
    TranslationProvider,
    TranslationRequest,
    Usage,
)
from app.services.terminology import TerminologyService

logger = logging.getLogger(__name__)

TRANSLATING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

MEMORY_SOURCE = "memory"

# Состояния, в которых документ занят процессом. Они ставятся на время
# работы и снимаются по её окончании; если процесс упал, снять их некому.
IN_PROGRESS = (DocumentStatus.PARSING, DocumentStatus.TRANSLATING)


def page_size(requested: int | None, *, default: int, maximum: int) -> int:
    """Сколько сегментов брать за вызов.

    Отсутствие значения — умолчание из настроек, а не «всё»: клиент, не
    знающий про порции, всё равно должен уложиться в предел прокси.
    Превышение потолка — ошибка запроса, а не тихое урезание: молча
    переведя двадцать тысяч вместо запрошенных пятидесяти, ответ обманул бы
    цикл клиента, который ждёт ровно столько, сколько просил.
    """
    if requested is None:
        return default

    if requested < 1:
        raise InvalidInputError("limit должен быть не меньше 1")

    if requested > maximum:
        raise InvalidInputError(
            f"limit={requested} превышает потолок {maximum} сегментов за вызов "
            "(TRANSLATION_MAX_SEGMENTS_PER_RUN)"
        )

    return requested


def is_stale(updated_at: datetime, *, now: datetime, threshold: timedelta) -> bool:
    """Давно ли документ подавал признаки жизни.

    Живой прогон отмечается в документе после каждой пачки; документ,
    молчащий дольше порога, — это упавший процесс. Порог задан снаружи,
    а не читается здесь из настроек, чтобы правило проверялось без них.
    """
    return now - updated_at >= threshold


def settled_status(*, total: int, untranslated: int) -> DocumentStatus:
    """Состояние документа по его сегментам.

    Применяется всюду, где документ выходит из «переводится» или
    «разбирается»: после порции, после срыва, при восстановлении на старте.
    Одно правило на все случаи, иначе они разойдутся.

    Отдельного состояния «частично переведён» у документа нет — это новое
    значение нативного перечисления в базе, а значит миграция. Пока
    остались непереведённые сегменты, документ «разобран»: следующий вызов
    перевода его продолжит; доля сделанного видна по `progress`. Когда
    непереведённых не осталось — «на вычитке»: перевод принимает человек.
    """
    if total == 0:
        return DocumentStatus.UPLOADED

    if untranslated > 0:
        return DocumentStatus.PARSED

    return DocumentStatus.REVIEW


@dataclass(frozen=True, slots=True)
class Recovered:
    """Документ, возвращённый из подвисшего состояния при старте."""

    document_id: uuid.UUID
    previous: DocumentStatus
    status: DocumentStatus


async def recover_interrupted(session: AsyncSession) -> list[Recovered]:
    """Снять отметки «разбирается» и «переводится», оставшиеся от убитого процесса.

    Вызывается при старте приложения. Работает по всем организациям, а не
    через контекст запроса: при старте запроса нет, а подвисший документ у
    любого клиента одинаково не даёт ни продолжить, ни повторить.

    Состояние берётся по данным, а не «как было до»: после падения на
    середине книги часть сегментов уже переведена и оплачена, и вернуть
    документ в «разобран» с сохранением сегментов честнее, чем в исходное
    с их потерей. Разбор пишет сегменты одной транзакцией, поэтому у
    прерванного разбора их либо нет, либо это полный набор прежнего.
    """
    hung = list(await session.scalars(select(Document).where(Document.status.in_(IN_PROGRESS))))
    if not hung:
        return []

    counts = await session.execute(
        select(
            Segment.document_id,
            func.count(),
            func.count().filter(Segment.status == SegmentStatus.NEW),
        )
        .where(Segment.document_id.in_([document.id for document in hung]))
        .group_by(Segment.document_id)
    )
    by_document = {document_id: (int(total), int(new)) for document_id, total, new in counts.all()}

    recovered: list[Recovered] = []

    for document in hung:
        total, untranslated = by_document.get(document.id, (0, 0))
        status = settled_status(total=total, untranslated=untranslated)

        recovered.append(Recovered(document.id, document.status, status))
        logger.warning(
            "Документ %s застрял в «%s» после прерванного процесса: возвращён в «%s» "
            "(сегментов %d, непереведённых %d)",
            document.id,
            document.status.value,
            status.value,
            total,
            untranslated,
        )
        document.status = status

    await session.commit()

    return recovered


@dataclass(slots=True)
class TranslationSummary:
    """Чем закончился перевод. Отдаётся клиенту и годится для счёта денег."""

    # Сколько сегментов взято в работу этим вызовом — не всего в документе.
    total: int
    from_memory: int
    from_provider: int
    flagged: int
    unique_texts: int
    # Сколько текстов реально ушло провайдеру. Не то же самое, что
    # from_provider: тот считает СЕГМЕНТЫ, получившие перевод от модели, а
    # повторяющийся сегмент получает его, не стоив отдельного обращения.
    provider_calls: int

    # Сколько непереведённых осталось после вызова. По этому числу клиент
    # решает, звать ли ещё раз: ноль — книга переведена целиком.
    remaining: int
    # Состояние документа после вызова: «разобран», если остаток есть,
    # «на вычитке», если нет.
    status: DocumentStatus

    # Потрачено на этот запуск. Ноль у заглушки — она ничего и не тратит.
    usage: Usage = field(default_factory=Usage)

    @property
    def saved_calls(self) -> int:
        """Сколько обращений к модели не понадобилось.

        Наивный перевод стоил бы одного обращения на сегмент. Разница с
        реальным числом обращений — это и есть то, за что не заплачено:
        повторы внутри документа плюс совпадения с памятью.
        """
        return self.total - self.provider_calls


@dataclass(slots=True)
class _RunStats:
    """Счётчики одной порции — до того, как стал известен остаток."""

    from_memory: int = 0
    from_provider: int = 0
    unique_texts: int = 0
    provider_calls: int = 0
    usage: Usage = field(default_factory=Usage)


class TranslationService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, provider: TranslationProvider
    ) -> None:
        super().__init__(session, context)
        self._provider = provider

    async def translate(
        self,
        document_id: uuid.UUID,
        *,
        limit: int | None = None,
        force: bool = False,
        ignore_terminology: bool = False,
    ) -> TranslationSummary:
        """Перевести очередную порцию документа.

        `force` делает две вещи, и обе — осознанный шаг. На документе, у
        которого непереведённых не осталось, он сбрасывает сегменты в
        непереведённые — включая правленые и принятые — и переводит первую
        порцию заново. На документе с непереведёнными он их просто
        продолжает: иначе цикл клиента, передающий `force` в каждом вызове,
        сбрасывал бы только что переведённое и не кончался бы никогда.
        На документе, зависшем в «переводится» дольше порога, `force`
        снимает отметку и продолжает — без сброса: тот, кто лечит зависший
        прогон, не просил переводить книгу заново.
        """
        self._context.require(*TRANSLATING_ROLES)

        settings = get_settings()
        limit = page_size(
            limit,
            default=settings.translation_default_limit,
            maximum=settings.translation_max_segments_per_run,
        )

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        if document.status in (DocumentStatus.UPLOADED, DocumentStatus.PARSING):
            raise ConflictError("Документ ещё не разобран на сегменты")

        if not ignore_terminology:
            # Терминологический проход либо не запускался (тогда кандидатов
            # нет и проверка молчит), либо запускался и не доведён до конца.
            # Второе — это перевод поверх нерешённого словаря, ровно та
            # ошибка, ради которой проход и заводился.
            undecided = await TerminologyService(self._session, self._context).undecided(
                document.id
            )
            if undecided:
                raise ConflictError(
                    f"Терминологический проход не закончен: {undecided} кандидатов без решения"
                )

        project = await self._session.scalar(
            self.scoped(Project).where(Project.id == document.project_id)
        )
        if project is None:
            raise NotFoundError("Проект не найден")

        glossary = await GlossaryService(self._session, self._context).load(
            project_id=document.project_id,
            source_language=project.source_language,
            target_language=project.target_language,
        )

        previous = document.status
        await self._claim(document, unlock_stale=force)

        try:
            untranslated = await self._count_untranslated(document.id)

            # Сброс — только на документе, где переводить больше нечего, и
            # не на зависшем: см. описание метода.
            if force and untranslated == 0 and previous is not DocumentStatus.TRANSLATING:
                untranslated = await self._reset_translated(document.id)

            segments = await self._select(document.id, limit)

            stats = (
                await self._run(
                    document,
                    segments,
                    glossary=glossary,
                    source_language=project.source_language,
                    target_language=project.target_language,
                )
                if segments
                else _RunStats()
            )
        except BaseException:
            # Отметку «переводится» надо снять, иначе сорвавшийся прогон
            # запирает документ навсегда: следующий запуск будет натыкаться
            # на собственную же метку. Сначала откат: если упала сама база,
            # сессия в нерабочем состоянии, и без отката не пройдёт и это.
            # Состояние — по данным: переведённые пачки уже зафиксированы.
            await self._session.rollback()
            await self._settle(document.id)
            raise

        remaining = await self._count_untranslated(document.id)

        if segments or previous is DocumentStatus.TRANSLATING:
            status = await self._settle(document.id)
        else:
            # Переводить было нечего — документ остаётся каким был. Иначе
            # повторный вызов на принятой книге вернул бы её на вычитку.
            status = await self._settle(document.id, keep=previous)

        flagged = sum(1 for segment in segments if segment.status is SegmentStatus.FLAGGED)

        return TranslationSummary(
            total=len(segments),
            from_memory=stats.from_memory,
            from_provider=stats.from_provider,
            flagged=flagged,
            unique_texts=stats.unique_texts,
            provider_calls=stats.provider_calls,
            remaining=remaining,
            status=status,
            usage=stats.usage,
        )

    async def _claim(self, document: Document, *, unlock_stale: bool) -> None:
        """Занять документ под перевод.

        Условным обновлением, а не присваиванием: два одновременных запроса
        прочитали бы одно и то же состояние и принялись бы переводить одни и
        те же сегменты — счёт двойной, а правки затрут друг друга. Условие
        проверяет сама база, и выигрывает ровно один.

        Зависший документ берётся тем же условием, а не отдельным шагом:
        снять отметку и поставить свою двумя запросами — это та же гонка,
        только между двумя лечащими.
        """
        settings = get_settings()
        threshold = timedelta(minutes=settings.translation_stale_minutes)
        now = datetime.now(UTC)

        # 🔥 Прежнее состояние читается ДО обновления. Обновление через ORM
        # сверяет условие по объектам в сессии и подтягивает изменения в
        # сам объект: после него `document.status` — это то, что мы сейчас
        # записали, а не то, что было. Проверка «а не был ли он уже занят»
        # после обновления срабатывала бы на каждом обычном запуске, и
        # предупреждение о перехвате зависшего прогона кричало бы всегда.
        was_running = document.status is DocumentStatus.TRANSLATING
        silent_since = document.updated_at

        free = Document.status != DocumentStatus.TRANSLATING
        condition = or_(free, Document.updated_at <= now - threshold) if unlock_stale else free

        claimed = await self._session.execute(
            update(Document)
            .where(Document.id == document.id, condition)
            .values(status=DocumentStatus.TRANSLATING, updated_at=now)
        )

        if claimed.rowcount == 0:
            hint = (
                " Прогон не подаёт признаков жизни дольше "
                f"{settings.translation_stale_minutes} мин: если он прерван, "
                "повторите с force=true."
                if is_stale(silent_since, now=now, threshold=threshold)
                else " Дождитесь окончания прогона."
            )
            raise ConflictError("Документ уже переводится." + hint)

        if was_running:
            logger.warning(
                "Документ %s взят повторно: прежний прогон молчал с %s",
                document.id,
                silent_since.isoformat(),
            )

        await self._session.commit()
        # Состояние объекта приводится к строке в базе: сверка по сессии
        # покрывает не всякое условие, и полагаться на неё как на гарантию
        # нельзя — а дальше по коду документ читается как источник правды.
        await self._session.refresh(document)

    async def _count_untranslated(self, document_id: uuid.UUID) -> int:
        query = (
            select(func.count())
            .select_from(Segment)
            .where(
                Segment.organization_id == self.organization_id,
                Segment.document_id == document_id,
                Segment.status == SegmentStatus.NEW,
            )
        )

        return int(await self._session.scalar(query) or 0)

    async def _reset_translated(self, document_id: uuid.UUID) -> int:
        """Вернуть все сегменты документа в непереведённые.

        Меняется состояние, а не текст: прежний перевод остаётся в строке до
        тех пор, пока его не заменит новый, — если прогон сорвётся, книга не
        окажется пустой. Находки проверок снимаются: они относятся к
        переводу, который объявлен устаревшим.
        """
        await self._session.execute(
            update(Segment)
            .where(
                Segment.organization_id == self.organization_id,
                Segment.document_id == document_id,
                Segment.status != SegmentStatus.NEW,
            )
            .values(status=SegmentStatus.NEW, quality=None, quality_score=None)
        )
        await self._session.commit()

        return await self._count_untranslated(document_id)

    async def _select(self, document_id: uuid.UUID, limit: int) -> list[Segment]:
        """Очередная порция: непереведённые сегменты в порядке документа.

        Только непереведённые, и при `force` тоже: правку человека и
        принятые сегменты продолжение не трогает, а «перевести заново»
        выражается сбросом в непереведённые, а не отдельной выборкой.
        Порядок документный, чтобы порция была связным куском книги —
        соседям это важно.
        """
        query = (
            self.scoped(Segment)
            .where(Segment.document_id == document_id, Segment.status == SegmentStatus.NEW)
            .order_by(Segment.position)
            .limit(limit)
        )

        return list(await self._session.scalars(query))

    async def _settle(
        self, document_id: uuid.UUID, *, keep: DocumentStatus | None = None
    ) -> DocumentStatus:
        """Снять отметку «переводится», выставив состояние по данным.

        Прямым обновлением, а не через объект: после отката сессии объект
        документа просрочен, а обращаться к базе после срыва нужно ровно
        одним запросом.
        """
        if keep is None:
            total = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(Segment)
                    .where(
                        Segment.organization_id == self.organization_id,
                        Segment.document_id == document_id,
                    )
                )
                or 0
            )
            keep = settled_status(
                total=total, untranslated=await self._count_untranslated(document_id)
            )

        await self._session.execute(
            update(Document)
            .where(Document.id == document_id, Document.organization_id == self.organization_id)
            .values(status=keep)
        )
        await self._session.commit()

        return keep

    async def _run(
        self,
        document: Document,
        segments: list[Segment],
        *,
        glossary: Glossary,
        source_language: str,
        target_language: str,
    ) -> _RunStats:
        memory = TranslationMemory(self._session, self._context)

        # Одинаковые сегменты собираются вместе: переводится один, результат
        # получают все. Ключ — отпечаток, а не текст: сегменты, различающиеся
        # только пробелами, для перевода одинаковы.
        groups: dict[str, list[Segment]] = {}
        for segment in segments:
            groups.setdefault(fingerprint(segment.source_text), []).append(segment)

        known = await memory.lookup(
            [group[0].source_text for group in groups.values()],
            source_language=source_language,
            target_language=target_language,
        )

        stats = _RunStats(unique_texts=len(groups))
        used_units: list[uuid.UUID] = []
        pending: list[tuple[str, list[Segment]]] = []

        for digest, group in groups.items():
            unit = known.get(digest)
            if unit is None:
                pending.append((digest, group))
                continue

            for segment in group:
                self._apply(
                    segment, unit.target_text, MEMORY_SOURCE, SegmentStatus.MEMORY, glossary
                )
                stats.from_memory += 1

            used_units.append(unit.id)

        await memory.count_hits(used_units)
        # Подстановки из памяти фиксируются до первого обращения к модели:
        # это уже результат, и отказ провайдера на первой же пачке не должен
        # его отменять.
        await self._session.commit()

        stats.from_provider = sum(len(group) for _, group in pending)
        stats.provider_calls = len(pending)

        if pending:
            # Соседи нужны только тому, что уходит модели: подстановка из
            # памяти в контексте не нуждается, и лишний проход по документу
            # ради неё делать незачем.
            context = await self._neighbourhood(document.id)
            batch_size = get_settings().translation_batch_size

            for start in range(0, len(pending), batch_size):
                chunk = pending[start : start + batch_size]

                pairs, spent = await self._translate_chunk(
                    chunk,
                    glossary=glossary,
                    context=context,
                    source_language=source_language,
                    target_language=target_language,
                )

                # Память, расход и отметка живого прогона — после КАЖДОЙ
                # пачки, одной транзакцией с самими переводами. Прогон, упавший
                # на десятой пачке, оставляет девять оплаченных в учёте;
                # запись в конце теряла бы их все.
                await memory.remember(
                    pairs,
                    source_language=source_language,
                    target_language=target_language,
                    origin=self._provider.name,
                )
                self._add_usage(document, spent)
                await self._session.commit()

                stats.usage = stats.usage + spent

        await self._check_expansions(document.id, glossary)
        await self._session.commit()

        return stats

    async def _translate_chunk(
        self,
        chunk: list[tuple[str, list[Segment]]],
        *,
        glossary: Glossary,
        context: dict[uuid.UUID, Neighbourhood],
        source_language: str,
        target_language: str,
    ) -> tuple[list[tuple[str, str]], Usage]:
        """Отдать одну пачку модели и разложить ответ по сегментам.

        Возвращает пары для памяти и расход пачки: считать их выше по
        стеку не по чему — ответ провайдера живёт здесь.
        """
        requests = [
            TranslationRequest(
                source_text=group[0].source_text,
                source_language=source_language,
                target_language=target_language,
                terms=glossary.match(group[0].source_text),
                kind=group[0].kind.value,
                # Контекст берётся у первого вхождения: у повторяющегося
                # сегмента соседи разные, а перевод обязан быть один.
                # Для повтора это и не потеря — предупреждение, которое
                # повторяется сорок раз, от соседей не зависит.
                context=context.get(group[0].id, EMPTY_CONTEXT),
            )
            for _, group in chunk
        ]

        batch = await self._provider.translate(requests)

        if len(batch.texts) != len(requests):
            raise ConflictError(
                "Провайдер вернул другое число переводов: "
                f"ожидалось {len(requests)}, получено {len(batch.texts)}"
            )

        pairs: list[tuple[str, str]] = []

        for (_, group), answer in zip(chunk, batch.texts, strict=True):
            for segment in group:
                self._apply(segment, answer, self._provider.name, SegmentStatus.MACHINE, glossary)

            pairs.append((group[0].source_text, answer))

        return pairs, batch.usage

    def _add_usage(self, document: Document, spent: Usage) -> None:
        """Прибавить расход пачки к итогу документа и отметить, что прогон жив.

        Нарастающим итогом, а не заменой: книгу переводят в несколько
        заходов — сначала целиком, потом добавленную главу, — и стоимость
        документа складывается из всех.

        Отметка времени ставится всегда, даже при нулевом расходе у
        заглушки: по ней зависший прогон отличают от длинного, и молчащий
        документ с живым прогоном был бы принят за брошенный.
        """
        document.input_tokens += spent.input_tokens
        document.output_tokens += spent.output_tokens
        document.cached_input_tokens += spent.cached_input_tokens
        document.cache_write_tokens += spent.cache_write_tokens
        document.translated_by = self._provider.name
        document.updated_at = datetime.now(UTC)

    def _apply(
        self,
        segment: Segment,
        target_text: str,
        source: str,
        status: SegmentStatus,
        glossary: Glossary,
    ) -> None:
        segment.target_text = target_text
        segment.translation_source = source

        findings = checks.run_checks(
            segment.source_text, target_text, glossary=glossary, kind=segment.kind
        )

        # Помечаем, а не переспрашиваем модель на месте: решение, что делать
        # с находкой — поправить руками или перевести заново, — принимается
        # не здесь.
        segment.status = SegmentStatus.FLAGGED if findings else status
        segment.quality = checks.as_json(findings)
        segment.quality_score = checks.score(findings) if findings else None

    async def _neighbourhood(self, document_id: uuid.UUID) -> dict[uuid.UUID, Neighbourhood]:
        """Собрать окружение каждого сегмента документа.

        Читается весь документ, а не только то, что переводится сейчас:
        соседом непереведённого сегмента может быть давно готовый, и без
        него контекст рвётся ровно на границе прошлого запуска.
        """
        size = get_settings().translation_context_segments

        segments = list(
            await self._session.scalars(
                self.scoped(Segment)
                .where(Segment.document_id == document_id)
                .order_by(Segment.position)
            )
        )

        context: dict[uuid.UUID, Neighbourhood] = {}
        heading: str | None = None

        for index, segment in enumerate(segments):
            context[segment.id] = Neighbourhood(
                before=tuple(item.source_text for item in segments[max(0, index - size) : index]),
                after=tuple(item.source_text for item in segments[index + 1 : index + 1 + size]),
                heading=heading,
            )

            # Заголовок обновляется после того, как записан контекст: для
            # самого заголовка предметную область задаёт предыдущий, а не он
            # сам.
            if segment.kind is SegmentKind.HEADING:
                heading = segment.source_text

        return context

    async def _check_expansions(self, document_id: uuid.UUID, glossary: Glossary) -> None:
        """Проверить, что аббревиатуры раскрыты при первом употреблении.

        Проверка документная, а не посегментная: «первое употребление»
        существует только в масштабе всего документа, и по одному сегменту
        сказать, первый он или сороковой, нельзя.

        Идём по всему документу, а не по переведённому в этот раз: первое
        вхождение могло достаться из памяти ещё в прошлый запуск, и
        требовать раскрытия от сорокового по счёту сегмента было бы ровно
        наоборот.
        """
        expandable = {term.source for term in glossary.terms if term.expand_on_first_use}
        if not expandable:
            return

        segments = list(
            await self._session.scalars(
                self.scoped(Segment)
                .where(Segment.document_id == document_id)
                .order_by(Segment.position)
            )
        )

        seen: set[str] = set()

        for segment in segments:
            if not segment.target_text:
                continue

            for term in glossary.match(segment.source_text):
                if term.source not in expandable or term.source in seen:
                    continue

                seen.add(term.source)
                finding = checks.first_use_finding(term, segment.target_text)

                if finding is not None:
                    self._add_finding(segment, finding)

    @staticmethod
    def _add_finding(segment: Segment, finding: checks.Finding) -> None:
        """Добавить находку к сегменту, не потеряв прежние."""
        previous = [
            checks.Finding(check=str(item["check"]), message=str(item["message"]))
            for item in (segment.quality or {}).get("findings", [])
        ]

        findings = [*previous, finding]

        segment.status = SegmentStatus.FLAGGED
        segment.quality = checks.as_json(findings)
        segment.quality_score = checks.score(findings)
