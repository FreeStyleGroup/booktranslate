"""Отчёт о расходе.

Токены хранятся, деньги считаются на лету — правило из `pricing.py`, и
здесь оно же: в базе лежат счётчики, а стоимость собирается при запросе по
той модели, которой книгу переводили. Пересчитывать потраченное задним
числом по новому прейскуранту значит подделывать отчёт.

🔥 **Разрез по времени — по месяцу загрузки книги, и так и написано.**
Отдельной записи «когда потратили» в базе нет: счётчики документа растут
при каждом прогоне и хранятся итогом. Группировать их по `updated_at`
нельзя — правка редактора через месяц утащила бы весь расход книги в
другой месяц. `created_at` не меняется никогда, поэтому разрез по нему
устойчив; что он означает именно загрузку, а не оплату, сказано и в
подписи на экране.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.models.document import Document
from app.models.project import Project
from app.services.base import TenantService
from app.services.pricing import estimate_usd
from app.services.providers import Usage

# Сколько книг показывать в разборе. Отчёт читают, чтобы понять, на что
# ушли деньги, а это всегда несколько самых дорогих: хвост из сотни
# копеечных книг ответа на этот вопрос не добавляет.
TOP_DOCUMENTS = 12

# Глубина разреза по времени. Год — столько, сколько имеет смысл сравнивать
# в одном масштабе; что было раньше, попадает в общий итог.
MONTHS = 12

# Книга, у которой переводчик не записан. Не «неизвестная модель»: модель
# не вызывалась вовсе — всё закрыли память переводов и повторы внутри
# книги. Разница видна в отчёте: у первого расход неизвестен, у второго
# его нет.
NO_MODEL = "без модели"


@dataclass(frozen=True, slots=True)
class Money:
    """Токены и то, во что они обошлись.

    Стоимость может быть неизвестна — у заглушки и у модели вне
    прейскуранта, — и `None` здесь честнее нуля: бесплатное и неизвестное
    это разные вещи.
    """

    usage: Usage
    usd: float | None


@dataclass(frozen=True, slots=True)
class DocumentSpend:
    document_id: uuid.UUID
    title: str
    project_name: str
    translated_by: str | None
    money: Money


@dataclass(frozen=True, slots=True)
class ModelSpend:
    model: str
    documents: int
    money: Money


@dataclass(frozen=True, slots=True)
class MonthSpend:
    # «2026-09» — разбирается витриной в название месяца.
    month: str
    money: Money
    # Из чего сложился месяц. Без этого столбец отвечает «сколько», но не
    # «на что», — а на вопрос «почему в марте вдвое дороже» отвечает
    # именно разбивка: сменили модель или перевели вдвое больше.
    by_model: list[ModelSpend]


@dataclass(slots=True)
class UsageReport:
    total: Money
    # Сколько книг вообще переводилось моделью: по нему видно, что итог
    # собран не с одной.
    documents: int
    by_month: list[MonthSpend] = field(default_factory=list)
    by_model: list[ModelSpend] = field(default_factory=list)
    by_document: list[DocumentSpend] = field(default_factory=list)


def _money(usage: Usage, model: str | None) -> Money:
    """Во что обошлись эти токены.

    Без модели считать нечего: `translated_by` пусто ровно тогда, когда
    модель не вызывалась вовсе — всё закрыли память и повторы.
    """
    if model is None:
        return Money(usage=usage, usd=None)

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

    Неизвестная стоимость не превращается в ноль и не обнуляет известную:
    итог по книгам, переведённым разными моделями, остаётся суммой того,
    что удалось посчитать.
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


class UsageService(TenantService):
    """Расход рабочего пространства — по месяцам, моделям и книгам."""

    async def report(self) -> UsageReport:
        """Отчёт целиком, одним запросом к базе.

        Все три разреза считаются по одной выборке: документов с расходом
        столько же, сколько переведённых книг, то есть немного, а три
        запроса с одинаковым условием разошлись бы при первой же правке
        условия.
        """
        rows = (
            await self._session.execute(
                select(
                    Document.id,
                    Document.title,
                    Document.translated_by,
                    Document.input_tokens,
                    Document.output_tokens,
                    Document.cached_input_tokens,
                    Document.cache_write_tokens,
                    func.to_char(Document.created_at, "YYYY-MM"),
                    Project.name,
                )
                .join(Project, Project.id == Document.project_id)
                .where(
                    Document.organization_id == self.organization_id,
                    # Книги без единого потраченного токена в отчёт о
                    # расходе не входят: строка с четырьмя нулями ничего не
                    # сообщает, а список делает длиннее.
                    (Document.input_tokens + Document.output_tokens) > 0,
                )
                .order_by(Document.created_at.desc())
            )
        ).all()

        spends = [
            DocumentSpend(
                document_id=row[0],
                title=row[1],
                project_name=row[8],
                translated_by=row[2],
                money=_money(
                    Usage(
                        input_tokens=row[3],
                        output_tokens=row[4],
                        cached_input_tokens=row[5],
                        cache_write_tokens=row[6],
                    ),
                    row[2],
                ),
            )
            for row in rows
        ]
        months = [row[7] for row in rows]

        return UsageReport(
            total=self._sum(spend.money for spend in spends),
            documents=len(spends),
            by_month=self._by_month(spends, months),
            by_model=self._by_model(spends),
            by_document=self._most_expensive(spends),
        )

    @staticmethod
    def _sum(items: Iterable[Money]) -> Money:
        total = EMPTY

        for money in items:
            total = _add(total, money)

        return total

    @classmethod
    def _by_month(cls, spends: list[DocumentSpend], months: list[str]) -> list[MonthSpend]:
        """Расход по месяцам с разбивкой по моделям — старые слева.

        Разбивка внутри месяца не украшение: расход вырос либо потому, что
        перевели больше, либо потому, что сменили модель, и различить это
        можно только так.
        """
        grouped: dict[str, list[DocumentSpend]] = {}

        for spend, month in zip(spends, months, strict=True):
            grouped.setdefault(month, []).append(spend)

        return [
            MonthSpend(
                month=month,
                money=cls._sum(spend.money for spend in grouped[month]),
                by_model=cls._by_model(grouped[month]),
            )
            for month in sorted(grouped)[-MONTHS:]
        ]

    @classmethod
    def _by_model(cls, spends: list[DocumentSpend]) -> list[ModelSpend]:
        """Чем переводили и во что это обошлось — дорогие сверху."""
        grouped: dict[str, list[DocumentSpend]] = {}

        for spend in spends:
            # Пусто — модель не вызывалась вовсе: всё закрыли память и
            # повторы. Это не «неизвестная модель», и называть это надо
            # своим именем.
            grouped.setdefault(spend.translated_by or NO_MODEL, []).append(spend)

        return sorted(
            (
                ModelSpend(
                    model=model,
                    documents=len(items),
                    money=cls._sum(item.money for item in items),
                )
                for model, items in grouped.items()
            ),
            key=lambda item: item.money.usage.input_tokens + item.money.usage.output_tokens,
            reverse=True,
        )

    @staticmethod
    def _most_expensive(spends: list[DocumentSpend]) -> list[DocumentSpend]:
        return sorted(
            spends,
            key=lambda spend: spend.money.usage.input_tokens + spend.money.usage.output_tokens,
            reverse=True,
        )[:TOP_DOCUMENTS]
