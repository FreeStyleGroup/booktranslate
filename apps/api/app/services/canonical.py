"""Канонический вид набора редакций и его сумма.

Проверка, сверка и выпуск отвечают на один вопрос: о каком именно тексте идёт речь. Ответ — набор
«блок → редакция» и его сумма. Порядок записи и вид сериализации на сумму влиять не должны, иначе
один и тот же набор получал бы разные суммы и выглядел бы изменившимся.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable


def canonical_json(value: object) -> str:
    """JSON, у которого один вид на одно значение: ключи по порядку, без лишних пробелов."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def revision_set_hash(pairs: Iterable[tuple[uuid.UUID, uuid.UUID | None]]) -> str:
    """Сумма набора «блок → редакция». Блок без перевода тоже входит: это часть состояния."""
    rows = sorted(
        (str(block), str(revision) if revision is not None else "") for block, revision in pairs
    )

    return hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()
