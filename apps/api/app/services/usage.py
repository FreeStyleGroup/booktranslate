"""Отчёт о расходе.

Токены хранятся, деньги считаются на лету — правило из `pricing.py` действует и
здесь: в базе лежат счётчики, а стоимость собирается по прейскуранту той модели,
которой переводили. Пересчитывать потраченное задним числом по новому прейскуранту
значит подделывать отчёт.

Расход записан в прогонах, поэтому разрез по времени честный: месяц запуска прогона,
а не загрузки книги. Прогон, начатый в конце месяца и законченный в следующем, идёт в
месяц запуска: на такой точности разрез и нужен.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.models.book import BookEdition
from app.models.project import Project
from app.models.translation import TranslationRun
from app.services.base import TenantService
from app.services.pricing import estimate_usd
from app.services.providers import Usage

# Сколько книг показывать в разборе. Отчёт читают, чтобы понять, куда ушли деньги, а
# это всегда несколько самых дорогих: хвост из копеечных ответа на этот вопрос не
# добавляет.
TOP_BOOKS = 12

# Глубина разреза по времени. Год — столько, сколько имеет смысл сравнивать в одном
# масштабе; что было раньше, попадает в общий итог.
MONTHS = 12


@dataclass(frozen=True, slots=True)
class Money:
    """Токены и то, во что они обошлись.

    Стоимость может быть неизвестна — у заглушки и у модели вне прейскуранта, — и
    `None` здесь честнее нуля: бесплатное и неизвестное — это разные вещи.
    """

    usage: Usage
    usd: float | None


@dataclass(frozen=True, slots=True)
class BookSpend:
    book_id: uuid.UUID
    title: str
    project_name: str
    # Какими моделями переводили, начиная с самой дорогой.
    models: list[str]
    money: Money


@dataclass(frozen=True, slots=True)
class ModelSpend:
    model: str
    books: int
    money: Money


@dataclass(frozen=True, slots=True)
class MonthSpend:
    # «2026-09» — разбирается витриной в название месяца.
    month: str
    money: Money
    # Из чего сложился месяц. Без этого столбец отвечает на «сколько», но не на
    # «почему в марте вдвое дороже»: сменили модель или перевели вдвое больше.
    by_model: list[ModelSpend]


@dataclass(slots=True)
class UsageReport:
    total: Money
    # Сколько книг вообще переводилось моделью.
    books: int
    by_month: list[MonthSpend] = field(default_factory=list)
    by_model: list[ModelSpend] = field(default_factory=list)
    by_book: list[BookSpend] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Row:
    """Расход одной книги одной моделью за один месяц."""

    book_id: uuid.UUID
    title: str
    project_name: str
    model: str
    month: str
    money: Money


def _money(usage: Usage, model: str) -> Money:
    """Во что обошлись эти токены."""
    return Money(
        usage=usage,
        usd=estimate_usd(
            model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_tokens=usage.cache_write_tokens,
        ),
    )


def _add(first: Money, second: Money) -> Money:
    """Сложить расход двух строк.

    Неизвестная стоимость не превращается в ноль и не обнуляет итог: итог по книгам,
    переведённым разными моделями, остаётся суммой того, что удалось посчитать.
    """
    usd = first.usd if second.usd is None else (first.usd or 0.0) + second.usd

    return Money(
        usage=Usage(
            input_tokens=first.usage.input_tokens + second.usage.input_tokens,
            output_tokens=first.usage.output_tokens + second.usage.output_tokens,
            cached_input_tokens=first.usage.cached_input_tokens + second.usage.cached_input_tokens,
            cache_write_tokens=first.usage.cache_write_tokens + second.usage.cache_write_tokens,
        ),
        usd=usd if usd is None else round(usd, 4),
    )


EMPTY = Money(usage=Usage(), usd=None)


def _weight(money: Money) -> int:
    return money.usage.input_tokens + money.usage.output_tokens


class UsageService(TenantService):
    """Расход рабочего пространства — по месяцам, моделям и книгам."""

    async def report(self) -> UsageReport:
        """Отчёт целиком, одним запросом к базе.

        Все разрезы считаются по одной выборке: два запроса с одинаковым условием
        разошлись бы при первой правке этого условия.
        """
        rows = await self._rows()

        return UsageReport(
            total=self._sum(row.money for row in rows),
            books=len({row.book_id for row in rows}),
            by_month=self._by_month(rows),
            by_model=self._by_model(rows),
            by_book=self._by_book(rows),
        )

    async def _rows(self) -> list[_Row]:
        month = func.to_char(TranslationRun.created_at, "YYYY-MM")
        spent = (
            await self._session.execute(
                select(
                    BookEdition.id,
                    BookEdition.title,
                    Project.name,
                    TranslationRun.model,
                    month,
                    func.sum(TranslationRun.input_tokens),
                    func.sum(TranslationRun.output_tokens),
                    func.sum(TranslationRun.cached_input_tokens),
                    func.sum(TranslationRun.cache_write_tokens),
                )
                .join(BookEdition, BookEdition.id == TranslationRun.book_id)
                .join(Project, Project.id == BookEdition.project_id)
                .where(
                    TranslationRun.organization_id == self.organization_id,
                    # Прогоны без единого потраченного токена в отчёт о расходе не
                    # входят: строка с нулями ничего не сообщает, а список делает длиннее.
                    (TranslationRun.input_tokens + TranslationRun.output_tokens) > 0,
                )
                .group_by(
                    BookEdition.id, BookEdition.title, Project.name, TranslationRun.model, month
                )
            )
        ).all()

        return [
            _Row(
                book_id=row[0],
                title=row[1],
                project_name=row[2],
                model=row[3],
                month=row[4],
                # 🔥 int(): сумму по целым Postgres возвращает типом numeric, и в Python
                # она приходит Decimal, а прейскурант умножает её на float.
                money=_money(
                    Usage(
                        input_tokens=int(row[5]),
                        output_tokens=int(row[6]),
                        cached_input_tokens=int(row[7]),
                        cache_write_tokens=int(row[8]),
                    ),
                    row[3],
                ),
            )
            for row in spent
        ]

    @staticmethod
    def _sum(items: Iterable[Money]) -> Money:
        total = EMPTY

        for money in items:
            total = _add(total, money)

        return total

    @classmethod
    def _by_month(cls, rows: Sequence[_Row]) -> list[MonthSpend]:
        """Расход по месяцам с разбивкой по моделям — старые первыми."""
        grouped: dict[str, list[_Row]] = {}

        for row in rows:
            grouped.setdefault(row.month, []).append(row)

        return [
            MonthSpend(
                month=month,
                money=cls._sum(row.money for row in grouped[month]),
                by_model=cls._by_model(grouped[month]),
            )
            for month in sorted(grouped)[-MONTHS:]
        ]

    @classmethod
    def _by_model(cls, rows: Sequence[_Row]) -> list[ModelSpend]:
        """Чем переводили и во что это обошлось — дорогие сверху."""
        grouped: dict[str, list[_Row]] = {}

        for row in rows:
            grouped.setdefault(row.model, []).append(row)

        return sorted(
            (
                ModelSpend(
                    model=model,
                    books=len({item.book_id for item in items}),
                    money=cls._sum(item.money for item in items),
                )
                for model, items in grouped.items()
            ),
            key=lambda item: _weight(item.money),
            reverse=True,
        )

    @classmethod
    def _by_book(cls, rows: Sequence[_Row]) -> list[BookSpend]:
        grouped: dict[uuid.UUID, list[_Row]] = {}

        for row in rows:
            grouped.setdefault(row.book_id, []).append(row)

        spends = [
            BookSpend(
                book_id=book_id,
                title=items[0].title,
                project_name=items[0].project_name,
                models=[item.model for item in cls._by_model(items)],
                money=cls._sum(item.money for item in items),
            )
            for book_id, items in grouped.items()
        ]

        return sorted(spends, key=lambda spend: _weight(spend.money), reverse=True)[:TOP_BOOKS]
