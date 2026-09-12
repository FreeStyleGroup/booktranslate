"""Схемы отчёта о расходе.

Токены и деньги едут вместе, но по-разному: токены — число, деньги —
оценка, которая может быть неизвестна. `null` в стоимости честнее нуля:
заглушка ничего не стоит, а модель вне прейскуранта стоит неизвестно
сколько, и показывать её как бесплатную нельзя.
"""

import uuid

from pydantic import BaseModel


class TokenCount(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    # Прочитанное из кэша отдельной строкой: оно стоит примерно десятую
    # часть обычного ввода, и сложенное с ним потеряло бы ровно то, ради
    # чего кэш заводили.
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0


class MoneyPublic(BaseModel):
    tokens: TokenCount
    # Оценка в долларах. `null` — модель не в прейскуранте или не
    # вызывалась вовсе.
    usd: float | None = None


class ModelSpendPublic(BaseModel):
    model: str
    documents: int
    money: MoneyPublic


class MonthSpendPublic(BaseModel):
    # «2026-09». Месяц загрузки книги, а не оплаты: отдельной записи «когда
    # потратили» в базе нет, а `created_at` не меняется никогда.
    month: str
    money: MoneyPublic
    by_model: list[ModelSpendPublic]


class DocumentSpendPublic(BaseModel):
    document_id: uuid.UUID
    title: str
    project_name: str
    # Чем переводили. `null` — модель не вызывалась: всё закрыли память и
    # повторы.
    translated_by: str | None
    money: MoneyPublic


class UsageReportPublic(BaseModel):
    total: MoneyPublic
    documents: int
    by_month: list[MonthSpendPublic]
    by_model: list[ModelSpendPublic]
    by_document: list[DocumentSpendPublic]
