"""Что меняет новая версия глоссария и какие блоки книги это задевает.

Чистые функции без базы: снимок версии на входе — записи терминов, на
выходе — контрольная сумма, список отличий и затронутые блоки. Так
правила сравнения проверяются на примерах, а не на собранной книге.

Отличием считается только то, что меняет требования к переводу
обязательного термина: сам перевод, допустимые варианты, разряд, регистр,
правило первого употребления и то, устоялось ли решение. Примечание,
область и источник — пояснения человеку; перевод из-за их правки не
становится неверным, и перепроверять из-за них книгу незачем.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.models.glossary_version import GlossaryVersionTerm, TermChangeKind
from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTerm, GlossaryTermStatus
from app.services.glossary import source_pattern

# Поля, смена которых меняет требования к переводу.
REQUIREMENT_FIELDS = (
    "target_term",
    "allowed_variants",
    "kind",
    "status",
    "case_sensitive",
    "first_use_rule",
)


@dataclass(frozen=True, slots=True)
class Entry:
    """Термин в том виде, в каком он входит в снимок версии."""

    source_term: str
    source_term_normalized: str
    target_term: str
    allowed_variants: tuple[str, ...]
    kind: GlossaryEntryKind
    status: GlossaryTermStatus
    mandatory: bool
    case_sensitive: bool
    first_use_rule: FirstUseRule
    domain: str | None
    note: str | None
    reference: str | None

    def record(self) -> dict[str, Any]:
        """Запись для журнала и сравнения: значения перечислений — строками."""
        return {
            "source_term": self.source_term,
            "target_term": self.target_term,
            "allowed_variants": list(self.allowed_variants),
            "kind": self.kind.value,
            "status": self.status.value,
            "mandatory": self.mandatory,
            "case_sensitive": self.case_sensitive,
            "first_use_rule": self.first_use_rule.value,
            "domain": self.domain,
            "note": self.note,
            "reference": self.reference,
        }

    def requirements(self) -> tuple[Any, ...]:
        record = self.record()

        return tuple(record[name] for name in REQUIREMENT_FIELDS)


def entry_of(record: GlossaryTerm | GlossaryVersionTerm) -> Entry:
    return Entry(
        source_term=record.source_term,
        source_term_normalized=record.source_term_normalized,
        target_term=record.target_term,
        allowed_variants=tuple(record.allowed_variants),
        kind=record.kind,
        status=record.status,
        mandatory=record.mandatory,
        case_sensitive=record.case_sensitive,
        first_use_rule=record.first_use_rule,
        domain=record.domain,
        note=record.note,
        reference=record.reference,
    )


def checksum(entries: Iterable[Entry]) -> str:
    """SHA-256 канонической записи снимка.

    Порядок — по нормализованному термину, а не по порядку выборки: тот
    же набор решений обязан давать ту же сумму, как бы его ни прочитали.
    """
    canonical = [
        [entry.source_term_normalized, entry.record()]
        for entry in sorted(entries, key=lambda entry: entry.source_term_normalized)
    ]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Change:
    kind: TermChangeKind
    before: Entry | None
    after: Entry | None

    @property
    def entry(self) -> Entry:
        """Запись, по которой термин ищут в тексте: новая, а у снятого — прежняя."""
        found = self.after or self.before
        assert found is not None  # noqa: S101 — изменение без обеих сторон не строится

        return found


def diff(before: Sequence[Entry], after: Sequence[Entry]) -> list[Change]:
    """Отличия обязательных терминов нового снимка от прежнего.

    Термин, переставший быть обязательным, для перевода снят: требование
    исчезло, и то, что переводилось под него, перепроверяют так же, как
    при удалении. Ставший обязательным — появился.
    """
    previous = {entry.source_term_normalized: entry for entry in before}
    current = {entry.source_term_normalized: entry for entry in after}
    changes = []

    for key in sorted(previous.keys() | current.keys()):
        was = previous.get(key)
        now = current.get(key)
        was_binding = was is not None and was.mandatory
        now_binding = now is not None and now.mandatory

        if now_binding and not was_binding:
            changes.append(Change(TermChangeKind.ADDED, was, now))
        elif was_binding and not now_binding:
            changes.append(Change(TermChangeKind.REMOVED, was, now))
        elif (
            was_binding
            and was is not None
            and now is not None
            and was.requirements() != now.requirements()
        ):
            changes.append(Change(TermChangeKind.CHANGED, was, now))

    return changes


@dataclass(frozen=True, slots=True)
class TextBlock:
    id: uuid.UUID
    text: str


def affected(blocks: Sequence[TextBlock], changes: Sequence[Change]) -> list[list[uuid.UUID]]:
    """Блоки, в тексте которых встречается термин каждого изменения.

    Ищется исходное написание — то, что стоит в оригинале и не меняется
    от версии к версии. Регистр — по обеим записям: если значимость
    регистра сменилась, затронуты блоки, найденные любым из двух способов.

    Перед регулярным выражением — грубая проверка подстрокой: она идёт в
    коде интерпретатора на C и отсекает почти всё. Изменений в версии
    бывают сотни, блоков в книге — тысячи, и регулярное выражение на
    каждую пару стоило бы минут.
    """
    folded = [block.text.casefold() for block in blocks]
    result = []

    for change in changes:
        sides = [entry for entry in (change.before, change.after) if entry is not None]
        source = change.entry.source_term
        strict = all(entry.case_sensitive for entry in sides)
        pattern = source_pattern(source, case_sensitive=strict)
        needle = source if strict else source.casefold()

        result.append(
            [
                block.id
                for block, lowered in zip(blocks, folded, strict=True)
                if needle in (block.text if strict else lowered) and pattern.search(block.text)
            ]
        )

    return result
