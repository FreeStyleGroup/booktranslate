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

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.memory import TranslationUnit
from app.services.base import TenantService

_WHITESPACE = re.compile(r"\s+")

# Сколько отпечатков спрашивать у базы за раз. Подобрано так, чтобы запрос
# оставался разбираемым: разбор списка `IN` на десятки тысяч значений
# занимает больше времени, чем поиск по индексу.
LOOKUP_BATCH = 1000


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
