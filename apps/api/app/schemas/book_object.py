"""Схемы специальных объектов главы."""

import uuid
from typing import Any

from pydantic import BaseModel

from app.models.block import BlockKind
from app.models.book_object import ObjectType, ReferenceKind


class BlockRefPublic(BaseModel):
    """Блок, относящийся к объекту: ячейка, листинг, подпись, упоминание."""

    id: uuid.UUID
    code: str
    full_code: str
    kind: BlockKind
    text: str
    active: bool
    # Место ячейки в сетке таблицы; у остальных блоков пусто.
    row: int | None
    column: int | None


class ObjectPublic(BaseModel):
    """Объект в составе версии мастера."""

    id: uuid.UUID
    chapter_id: uuid.UUID
    # `FIG001` и полный `CH03-FIG001`.
    code: str
    full_code: str
    type: ObjectType
    # Номер из подписи или из самой формулы — «3.2».
    label: str | None
    checksum: str
    active: bool
    # Сколько блоков версии стоит перед объектом, и код того, перед
    # которым он стоит; пусто — объект в конце главы.
    at: int
    before_code: str | None
    caption: str | None
    caption_code: str | None
    # Блоки-содержимое по порядку: ячейки таблицы, текст листинга.
    content_codes: list[str]
    references: int
    # Сетка таблицы, язык листинга, изображения рисунка, текст и дерево
    # формулы. Запись формулы как есть — только в карточке объекта.
    payload: dict[str, Any]


class MentionPublic(BaseModel):
    block: BlockRefPublic
    chapter_id: uuid.UUID
    kind: ReferenceKind
    phrase: str


class ObjectDetailPublic(ObjectPublic):
    """Объект со всем, что к нему относится, — в одной версии мастера."""

    book_id: uuid.UUID
    master_id: uuid.UUID
    master_label: str
    content: list[BlockRefPublic]
    caption_block: BlockRefPublic | None
    mentions: list[MentionPublic]
    # Объект, из которого этот получился при новой версии мастера.
    parent_code: str | None


class FoundObjectPublic(BaseModel):
    """Объект, найденный по коду, и где его показать."""

    book_id: uuid.UUID
    book_code: str
    chapter_id: uuid.UUID
    object_id: uuid.UUID
    full_code: str
