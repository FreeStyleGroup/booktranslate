"""Расход рабочего пространства."""

from fastapi import APIRouter

from app.api.deps import ContextDep, SessionDep
from app.schemas.usage import (
    DocumentSpendPublic,
    ModelSpendPublic,
    MoneyPublic,
    MonthSpendPublic,
    TokenCount,
    UsageReportPublic,
)
from app.services.usage import ModelSpend, Money, UsageService

router = APIRouter(tags=["usage"])


def _money(money: Money) -> MoneyPublic:
    return MoneyPublic(
        tokens=TokenCount(
            input_tokens=money.usage.input_tokens,
            output_tokens=money.usage.output_tokens,
            cached_input_tokens=money.usage.cached_input_tokens,
            cache_write_tokens=money.usage.cache_write_tokens,
        ),
        usd=money.usd,
    )


def _model(spend: ModelSpend) -> ModelSpendPublic:
    return ModelSpendPublic(model=spend.model, documents=spend.documents, money=_money(spend.money))


@router.get("/usage", response_model=UsageReportPublic)
async def usage_report(context: ContextDep, session: SessionDep) -> UsageReportPublic:
    """Во что обошёлся перевод: по месяцам, моделям и книгам.

    Токены хранятся, деньги считаются здесь и сейчас — по той модели,
    которой книгу переводили. Пересчитывать потраченное задним числом по
    новому прейскуранту значит подделывать отчёт, поэтому цены в базу не
    попадают вовсе.
    """
    report = await UsageService(session, context).report()

    return UsageReportPublic(
        total=_money(report.total),
        documents=report.documents,
        by_month=[
            MonthSpendPublic(
                month=month.month,
                money=_money(month.money),
                by_model=[_model(item) for item in month.by_model],
            )
            for month in report.by_month
        ],
        by_model=[_model(item) for item in report.by_model],
        by_document=[
            DocumentSpendPublic(
                document_id=spend.document_id,
                title=spend.title,
                project_name=spend.project_name,
                translated_by=spend.translated_by,
                money=_money(spend.money),
            )
            for spend in report.by_document
        ],
    )
