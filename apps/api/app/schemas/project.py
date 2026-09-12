"""Схемы проектов перевода."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Код языка по BCP 47: «en», «ru», «de-CH», «zh-Hans». Проверяется формой, а
# не списком: полный перечень языков и их вариантов в код не помещается и
# устаревает, а очевидный мусор форма отсекает.
LanguageCode = Annotated[str, Field(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$", max_length=20)]


# Название — строка в карточке и в заголовке: дольше ста двадцати знаков
# оно не название, а описание. Слово длиннее сорока знаков — не слово, а
# прижатая клавиша: ни одно настоящее название так не выглядит, а карточку
# такое слово рвёт, потому что переносить его негде.
NAME_MAX = 120
WORD_MAX = 40
DESCRIPTION_MAX = 1000


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=NAME_MAX)
    source_language: LanguageCode
    target_language: LanguageCode
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    # Короткое имя необязательно: по умолчанию берётся из названия. Задают
    # его тогда, когда адрес проекта уже где-то опубликован.
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)

    @model_validator(mode="after")
    def name_is_a_name(self) -> Self:
        self.name = " ".join(self.name.split())

        if len(self.name) < 2:
            raise ValueError("Название проекта — хотя бы два знака")

        if any(len(word) > WORD_MAX for word in self.name.split()):
            raise ValueError(f"Слово в названии длиннее {WORD_MAX} знаков — так не бывает")

        return self

    @model_validator(mode="after")
    def languages_differ(self) -> Self:
        # Проект «с русского на русский» — не перевод, а опечатка в форме.
        # Ловить её здесь дешевле, чем через неделю в отчёте.
        if self.source_language.lower() == self.target_language.lower():
            raise ValueError("Язык оригинала и язык перевода совпадают")

        return self


class ProjectPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    source_language: str
    target_language: str
    created_at: datetime
    updated_at: datetime
