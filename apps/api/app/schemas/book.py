"""Схемы изданий и комплекта исходников.

Комплект описан своими схемами, а не `DocumentPublic`: на этом экране
смотрят, из чего состоит книга и годятся ли файлы, а не как идёт перевод.
Расход токенов и доступные форматы выгрузки здесь были бы шумом.
"""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.book import BookStatus
from app.models.document import SourceFormat, SourceRole

# Пределы взяты от колонок: длиннее в базу всё равно не ляжет, а
# расхождение между проверкой и хранилищем даёт отказ уже после приёма.
TITLE_MAX = 500
AUTHOR_MAX = 300
EDITION_MAX = 200

# Слово длиннее шестидесяти знаков — не слово, а прижатая клавиша.
# Предел выше проектного: в названиях книг встречаются немецкие составные
# слова и латинские термины, и сорока знаков им мало.
WORD_MAX = 60


class BookCreate(BaseModel):
    title: Annotated[str, Field(min_length=2, max_length=TITLE_MAX)]
    author: Annotated[str | None, Field(default=None, max_length=AUTHOR_MAX)]
    # «2-е издание, 2021» — пометка, по которой отличают издания друг от
    # друга. Необязательна: у книги, выходившей один раз, её нет.
    edition_label: Annotated[str | None, Field(default=None, max_length=EDITION_MAX)]

    @model_validator(mode="after")
    def title_is_a_title(self) -> Self:
        self.title = " ".join(self.title.split())

        if len(self.title) < 2:
            raise ValueError("Название книги — хотя бы два знака")

        if any(len(word) > WORD_MAX for word in self.title.split()):
            raise ValueError(f"Слово в названии длиннее {WORD_MAX} знаков — так не бывает")

        return self


class BookPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    # Код уходит в номера замечаний (`BK01-CH03-ERR-0001`) и потому
    # показывается человеку: по нему он находит книгу по одному номеру.
    code: str
    title: str
    author: str | None
    edition_label: str | None
    source_language: str
    target_language: str
    status: BookStatus
    created_at: datetime
    updated_at: datetime


class BookPagePublic(BaseModel):
    """Страница списка изданий: сколько всего и что показано.

    Пределы выдачи возвращаются вместе со строками: по ним на экране
    считаются номера страниц, и считать их по тому, что просили, а не по
    тому, что отдали, значит однажды разойтись на единицу.
    """

    total: int
    limit: int
    offset: int
    items: list[BookPublic]


class SourceAttach(BaseModel):
    document_id: uuid.UUID
    role: SourceRole


class SourceRoleUpdate(BaseModel):
    role: SourceRole


class ValidationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    format_ok: bool
    has_text_layer: bool
    page_count: int | None
    # Название и автор так, как их объявляет сам файл. По ним сличают
    # источники: совпали — комплект собран верно.
    meta_title: str | None
    meta_author: str | None
    parser_version: str
    warnings: list[str]
    updated_at: datetime


class SourcePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str | None
    source_format: SourceFormat
    source_role: SourceRole | None
    size_bytes: int | None
    # Контрольная сумма видна человеку: по ней он убеждается, что в
    # комплекте тот самый файл, который присылали.
    content_hash: str | None
    # Пусто, пока файл не проверяли: проверка запускается отдельно, потому
    # что на большом PDF она занимает время.
    validation: ValidationPublic | None = None


class BookKitPublic(BaseModel):
    sources: list[SourcePublic]
    # Предупреждение о том, что источники похожи на разные издания.
    # Именно предупреждение: запрета здесь нет, решение принимает человек.
    mismatch: str | None
