"""Запись принятых решений.

Процесс перевода держится на утверждениях: границы главы, версия
глоссария, подтверждение ошибки, выпуск книги. Через полгода по каждому
нужно уметь ответить, кто и на каком основании его принял — без этого
выпуск нельзя считать воспроизводимым.

Событие кладётся в ту же транзакцию, что и само решение, поэтому здесь
нет фиксации. Отдельная фиксация журнала дала бы худшее из двух: запись о
решении, которого не случилось (откат после записи), либо решение без
записи (падение между фиксациями).
"""

import uuid
from typing import Any

from app.models.audit import AuditEvent
from app.services.base import TenantService


class AuditService(TenantService):
    def record(
        self,
        *,
        kind: str,
        subject_type: str,
        subject_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Записать решение текущего пользователя.

        `kind` — что решили (`book.created`), `subject_type` и
        `subject_id` — над чем. `payload` хранит основание: причину,
        прежнее и новое значение. Возвращённое событие ещё не сохранено —
        его сохранит фиксация вызывающего.
        """
        event = AuditEvent(
            organization_id=self.organization_id,
            actor_id=self._context.user.id,
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload or {},
        )

        self._session.add(event)

        return event
