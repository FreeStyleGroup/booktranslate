"""Память переводов.

Отвечает на единственный вопрос: «мы это уже переводили?». Совпадение ищется
по хешу нормализованного исходника — регистр и расстановка пробелов к смыслу
отношения не имеют, а без нормализации «Внимание!» и «Внимание !» считались бы
разными фразами и оплачивались дважды.

Нечёткое совпадение (похожий, но не тот же текст) сюда пока не входит: оно
требует либо расширения `pg_trgm`, либо векторного индекса, и его стоит
включать, когда будет на чём мерить пользу — на пустой памяти оно бесполезно.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.models.memory import TranslationUnit
from app.models.organization import Role
from app.services.base import TenantService
from app.services.errors import InvalidInputError, NotFoundError
from app.services.pricing import forecast
from app.services.providers import provider_name
from app.services.search import ESCAPE, contains
from app.services.workspace import model_for

_WHITESPACE = re.compile(r"\s+")

# Сколько отпечатков спрашивать у базы за раз. Подобрано так, чтобы запрос
# оставался разбираемым: разбор списка `IN` на десятки тысяч значений
# занимает больше времени, чем поиск по индексу.
LOOKUP_BATCH = 1000

# Происхождение пары, поправленной человеком. Такая пара вытесняет машинную
# и сама машинной не вытесняется.
HUMAN = "human"

# Править и снимать пары памяти — то же, что править перевод: редактор
# делает это в очереди замечаний, и здесь его право то же самое.
EDITING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER)


@dataclass(slots=True)
class MemoryPage:
    total: int
    items: list[TranslationUnit]


@dataclass(frozen=True, slots=True)
class MemorySummary:
    """Чего память стоит — в числах, которые показывают заказчику.

    `saved_characters` — знаки исходника, которые не ушли в модель: у
    каждой пары длина умножается на число раз, когда она пригодилась.
    `saved_usd` — во что они обошлись бы по текущей модели пространства;
    оценка сверху, как и смета, и по той же формуле.
    """

    units: int
    human_units: int
    hits: int
    saved_characters: int
    saved_usd: float | None


def normalize(text: str) -> str:
    """Вид текста, по которому сравниваются совпадения."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def fingerprint(text: str) -> str:
    """Отпечаток нормализованного текста для поиска по индексу."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


class TranslationMemory(TenantService):
    async def lookup(
        self, texts: list[str], *, source_language: str, target_language: str
    ) -> dict[str, TranslationUnit]:
        """Найти готовые переводы для набора текстов.

        Запрос один на весь набор, а не по одному на текст: на книге в
        несколько тысяч сегментов разница между одним запросом и тысячей —
        это разница между секундой и минутами.

        Ключ результата — отпечаток, а не исходный текст: у двух сегментов,
        различающихся только пробелами, отпечаток общий, и класть их в
        словарь по тексту значило бы потерять одно из совпадений.
        """
        hashes = {fingerprint(text) for text in texts}
        if not hashes:
            return {}

        query = self.scoped(TranslationUnit).where(
            TranslationUnit.source_language == source_language,
            TranslationUnit.target_language == target_language,
            TranslationUnit.source_hash.in_(hashes),
        )

        return {unit.source_hash: unit for unit in await self._session.scalars(query)}

    async def known(
        self, hashes: set[str], *, source_language: str, target_language: str
    ) -> set[str]:
        """Какие из отпечатков память уже закрывает.

        Отдельно от `lookup`, потому что вопрос другой: смете нужно число
        совпадений по всей книге, а не сами переводы, и тянуть ради него
        десять тысяч строк с текстом незачем.

        Отпечатки спрашиваются пачками: `IN` на двадцать тысяч значений
        разбирается дольше, чем выполняется сам запрос.
        """
        found: set[str] = set()
        batch = sorted(hashes)

        for start in range(0, len(batch), LOOKUP_BATCH):
            query = select(TranslationUnit.source_hash).where(
                TranslationUnit.organization_id == self.organization_id,
                TranslationUnit.source_language == source_language,
                TranslationUnit.target_language == target_language,
                TranslationUnit.source_hash.in_(batch[start : start + LOOKUP_BATCH]),
            )

            found.update(await self._session.scalars(query))

        return found

    async def remember(
        self,
        pairs: list[tuple[str, str]],
        *,
        source_language: str,
        target_language: str,
        origin: str,
    ) -> int:
        """Запомнить пары «исходник — перевод».

        Повтор не считается ошибкой: тот же текст мог встретиться в другом
        документе, и попытка записать его второй раз — обычное дело, а не
        сбой. Поэтому вставка с обновлением по конфликту, а не проверка
        перед вставкой: проверка не спасает от гонки двух переводов подряд.

        Перевод человека вытесняет машинный, обратное — нет: правка
        редактора надёжнее, и затирать её результатом следующей модели
        значит терять работу.
        """
        rows = []
        seen: set[str] = set()

        for source_text, target_text in pairs:
            if not source_text.strip() or not target_text.strip():
                continue

            digest = fingerprint(source_text)
            # Внутри одной пачки один и тот же отпечаток дважды приведёт к
            # «ON CONFLICT DO UPDATE command cannot affect row a second time».
            if digest in seen:
                continue
            seen.add(digest)

            rows.append(
                {
                    "id": uuid.uuid4(),
                    "organization_id": self.organization_id,
                    "source_language": source_language,
                    "target_language": target_language,
                    "source_hash": digest,
                    "source_text": source_text,
                    "target_text": target_text,
                    "origin": origin,
                }
            )

        if not rows:
            return 0

        statement = insert(TranslationUnit).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="translation_unit_source",
            set_={
                "target_text": statement.excluded.target_text,
                "origin": statement.excluded.origin,
            },
            where=(TranslationUnit.origin != "human") | (statement.excluded.origin == "human"),
        )

        await self._session.execute(statement)

        return len(rows)

    async def count_hits(self, unit_ids: list[uuid.UUID]) -> None:
        """Отметить, что переводы пригодились.

        Счётчик — не статистика ради статистики: по нему видно, что именно
        окупает память, и он же служит обоснованием скидки заказчику на
        повторный заказ.
        """
        if not unit_ids:
            return

        await self._session.execute(
            update(TranslationUnit)
            .where(
                TranslationUnit.organization_id == self.organization_id,
                TranslationUnit.id.in_(unit_ids),
            )
            .values(hits=TranslationUnit.hits + 1)
        )

    async def size(self, *, source_language: str, target_language: str) -> int:
        query = select(TranslationUnit.id).where(
            TranslationUnit.organization_id == self.organization_id,
            TranslationUnit.source_language == source_language,
            TranslationUnit.target_language == target_language,
        )

        return len((await self._session.scalars(query)).all())

    async def page(
        self,
        *,
        query: str | None = None,
        origin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> MemoryPage:
        """Страница памяти с отбором по тексту и происхождению.

        Первыми — пары, пригодившиеся чаще: по ним видно, что именно
        окупает память. `origin` — «human» либо «machine»: машинных
        происхождений много (по имени модели), а вопрос у человека один —
        правил ли это кто-то.
        """
        statement = self.scoped(TranslationUnit)

        if query:
            pattern = contains(query)
            statement = statement.where(
                or_(
                    TranslationUnit.source_text.ilike(pattern, escape=ESCAPE),
                    TranslationUnit.target_text.ilike(pattern, escape=ESCAPE),
                )
            )

        if origin == HUMAN:
            statement = statement.where(TranslationUnit.origin == HUMAN)
        elif origin is not None:
            statement = statement.where(TranslationUnit.origin != HUMAN)

        total = await self._count(statement)
        rows = await self._session.scalars(
            statement.order_by(TranslationUnit.hits.desc(), TranslationUnit.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return MemoryPage(total=total, items=list(rows))

    async def _count(self, statement: Select[tuple[TranslationUnit]]) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )

        return int(counted or 0)

    async def summary(self) -> MemorySummary:
        """Сколько память сберегла — по всему пространству."""
        row = (
            await self._session.execute(
                select(
                    func.count(TranslationUnit.id),
                    func.count(TranslationUnit.id).filter(TranslationUnit.origin == HUMAN),
                    func.coalesce(func.sum(TranslationUnit.hits), 0),
                    func.coalesce(
                        func.sum(func.length(TranslationUnit.source_text) * TranslationUnit.hits),
                        0,
                    ),
                ).where(TranslationUnit.organization_id == self.organization_id)
            )
        ).one()

        # Суммы из Postgres приходят Decimal: до умножения на цену их надо
        # привести к int, иначе оценка падает на первой же паре.
        saved_characters = int(row[3])
        model = provider_name(await model_for(self._session, self.organization_id))

        return MemorySummary(
            units=int(row[0]),
            human_units=int(row[1]),
            hits=int(row[2]),
            saved_characters=saved_characters,
            saved_usd=forecast(
                model,
                characters=saved_characters,
                context_segments=get_settings().translation_context_segments,
            ).usd,
        )

    async def update(self, unit_id: uuid.UUID, *, target_text: str) -> TranslationUnit:
        """Поправить перевод пары.

        Поправленная пара становится человеческой: дальше она вытесняет
        машинный вариант при совпадении и не вытесняется им — правка
        редактора надёжнее следующей модели.
        """
        self._context.require(*EDITING_ROLES)

        if not target_text.strip():
            raise InvalidInputError("Перевод не может быть пустым")

        unit = await self._get(unit_id)
        unit.target_text = target_text.strip()
        unit.origin = HUMAN

        await self._session.commit()
        await self._session.refresh(unit)

        return unit

    async def delete(self, unit_id: uuid.UUID) -> None:
        """Снять пару: следующий такой же текст уйдёт в модель заново."""
        self._context.require(*EDITING_ROLES)

        await self._session.delete(await self._get(unit_id))
        await self._session.commit()

    async def _get(self, unit_id: uuid.UUID) -> TranslationUnit:
        unit = await self._session.scalar(
            self.scoped(TranslationUnit).where(TranslationUnit.id == unit_id)
        )
        if unit is None:
            raise NotFoundError("Пара не найдена")

        return unit
