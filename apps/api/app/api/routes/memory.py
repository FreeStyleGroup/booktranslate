"""Память переводов: что уже переводили и во что это обошлось бы заново."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContextDep, SessionDep
from app.schemas.memory import (
    MemoryPagePublic,
    MemorySummaryPublic,
    TranslationUnitPublic,
    TranslationUnitUpdate,
)
from app.services.memory import TranslationMemory

router = APIRouter(tags=["memory"])


@router.get("/memory", response_model=MemoryPagePublic)
async def list_memory(
    context: ContextDep,
    session: SessionDep,
    query: Annotated[
        str | None, Query(max_length=300, description="Часть исходника или перевода")
    ] = None,
    origin: Annotated[
        str | None,
        Query(
            pattern="^(human|machine)$",
            description="Только правленные человеком либо только машинные",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoryPagePublic:
    """Пары «исходник — перевод» пространства, чаще пригодившиеся первыми.

    Со сводкой по всей памяти, а не по странице: сколько пар, сколько раз
    они пригодились и во что это обошлось бы по текущей модели. Сводка —
    то, что показывают заказчику как обоснование скидки на повторный заказ.
    """
    memory = TranslationMemory(session, context)
    page = await memory.page(query=query, origin=origin, limit=limit, offset=offset)

    return MemoryPagePublic(
        total=page.total,
        items=[TranslationUnitPublic.model_validate(unit) for unit in page.items],
        summary=MemorySummaryPublic.model_validate(await memory.summary()),
    )


@router.patch("/memory/{unit_id}", response_model=TranslationUnitPublic)
async def update_memory_unit(
    unit_id: uuid.UUID,
    payload: TranslationUnitUpdate,
    context: ContextDep,
    session: SessionDep,
) -> TranslationUnitPublic:
    """Поправить перевод пары. Поправленная становится человеческой и дальше
    вытесняет машинный вариант, а не наоборот."""
    unit = await TranslationMemory(session, context).update(
        unit_id, target_text=payload.target_text
    )

    return TranslationUnitPublic.model_validate(unit)


@router.delete("/memory/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_unit(
    unit_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> Response:
    """Снять пару: следующий такой же текст уйдёт в модель заново."""
    await TranslationMemory(session, context).delete(unit_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
