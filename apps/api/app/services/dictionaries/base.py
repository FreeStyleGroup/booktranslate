"""Общее для всех источников словаря.

Загруженная запись — это ещё не термин: у неё нет ни организации, ни
языковой пары, ни решения о том, применять ли её. Поэтому чтение файла
отделено от записи в базу: разбор форматов проверяется без базы вовсе, а
правила «чужое не затирает ручную работу» живут в одном месте, а не в
каждом разборщике.
"""

from dataclasses import dataclass, field

from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.services.errors import InvalidInputError


class DictionaryError(InvalidInputError):
    """Файл словаря не разобрался.

    Наследуется от доменной ошибки, а не заводится отдельным деревом: для
    клиента это 400 — файл принят, разобрать не вышло, — и превращать её в
    код ответа вручную в каждом обработчике незачем.
    """


@dataclass(frozen=True, slots=True)
class ImportedTerm:
    """Запись, прочитанная из внешнего источника."""

    source_term: str
    target_term: str
    kind: GlossaryEntryKind = GlossaryEntryKind.TERM
    # Загруженное приходит предложенным, а не подтверждённым: чужой словарь
    # верен не весь, а тот, кто его загрузил, за каждую строку не отвечает.
    # Источник, где статус указан явно (рабочий реестр), его и ставит.
    status: GlossaryTermStatus = GlossaryTermStatus.PROPOSED
    note: str | None = None
    reference: str | None = None
    expand_on_first_use: bool = False


@dataclass(slots=True)
class DictionaryContents:
    """Что вышло из файла: записи и причины, по которым что-то не взяли."""

    terms: list[ImportedTerm] = field(default_factory=list)
    # Причины пропуска, а не число: «пропущено 240 строк» человеку ничего не
    # говорит, а «нет перевода» — говорит, что колонки перепутаны местами.
    skipped: list[str] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.skipped.append(reason)
