"""Жизненный цикл замечания: какие переходы вообще бывают.

Таблицей, а не условиями по сервису: её можно прочитать целиком, сверить с процессом и
проверить на всех парах состояний. Произвольной смены статуса в API нет: статус меняется
только действиями, а каждое действие проходит эту таблицу. Какие условия нужны сверх
перехода (редакция, проверяющий, причина), решает сервис: они зависят от данных.

Модуль без базы и без сервиса намеренно: его же спрашивает витрина через список доступных
действий, и второй копии правил там нет.
"""

from collections.abc import Mapping

from app.models.issue import IssueStatus
from app.services.errors import ConflictError

# Подтвердить, отклонить и попросить уточнения можно только то, что ждёт решения: новое и
# открытое заново. Уточнение возвращается через «открыто заново»: у ответа есть причина и
# актуальная редакция, а у возврата в «новое» их негде было бы хранить.
TRANSITIONS: Mapping[IssueStatus, frozenset[IssueStatus]] = {
    IssueStatus.NEW: frozenset(
        {IssueStatus.CONFIRMED, IssueStatus.REJECTED, IssueStatus.NEEDS_CLARIFICATION}
    ),
    IssueStatus.NEEDS_CLARIFICATION: frozenset({IssueStatus.REOPENED}),
    IssueStatus.CONFIRMED: frozenset({IssueStatus.FIXED, IssueStatus.REOPENED}),
    IssueStatus.FIXED: frozenset({IssueStatus.VERIFIED, IssueStatus.REOPENED}),
    IssueStatus.VERIFIED: frozenset({IssueStatus.CLOSED, IssueStatus.REOPENED}),
    IssueStatus.CLOSED: frozenset({IssueStatus.REOPENED}),
    IssueStatus.REJECTED: frozenset({IssueStatus.REOPENED}),
    IssueStatus.REOPENED: frozenset(
        {IssueStatus.CONFIRMED, IssueStatus.REJECTED, IssueStatus.NEEDS_CLARIFICATION}
    ),
}

# Решение принято — по таким выпуск не держится. Всё остальное открыто.
DECIDED = frozenset({IssueStatus.CLOSED, IssueStatus.REJECTED})
OPEN = frozenset(IssueStatus) - DECIDED


def can_transition(current: IssueStatus, target: IssueStatus) -> bool:
    return target in TRANSITIONS[current]


def require_transition(current: IssueStatus, target: IssueStatus) -> None:
    """Отказ со словами, а не молчаливое «ничего не изменилось»: API отвечает 409."""
    if not can_transition(current, target):
        raise ConflictError(f"Из состояния «{current.value}» нельзя перейти в «{target.value}»")
