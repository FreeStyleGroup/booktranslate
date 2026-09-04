"""Проверка живости.

Два разных ответа на два разных вопроса. `/health` отвечает «процесс жив» и
не ходит в базу: по нему оркестратор решает, перезапускать ли контейнер, и
недоступность базы перезапуском не лечится. `/health/ready` отвечает «готов
принимать запросы» и базу проверяет — по нему балансировщик решает, слать ли
трафик.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment}


@router.get("/health/ready")
async def ready(response: Response, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — наружу уходит только факт отказа
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # Текст ошибки драйвера содержит строку подключения с паролем,
        # поэтому в ответ идёт только тип исключения, а подробности — в лог.
        return {"status": "unavailable", "reason": type(exc).__name__}

    return {"status": "ready"}
