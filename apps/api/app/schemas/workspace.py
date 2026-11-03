"""Схемы настроек рабочего пространства: чем переводить и чем делиться."""

from pydantic import BaseModel, Field

from app.models.qa import QAScope
from app.models.workspace import MemoryPublish


class ModelChoicePublic(BaseModel):
    id: str
    title: str
    note: str
    # Долларов за миллион токенов; пусто — модель вне прейскуранта.
    input_usd: float | None
    output_usd: float | None


class SubjectPublic(BaseModel):
    id: str
    title: str


class WorkspaceSettingsPublic(BaseModel):
    # Чем переводят на самом деле: выбранное либо умолчание площадки.
    translation_model: str
    # Что выбрало пространство. Пусто — идёт по умолчанию, и это отличается
    # от «выбрало то же, что и умолчание»: смена умолчания площадки первое
    # затронет, второе — нет.
    chosen_model: str | None
    default_model: str
    models: list[ModelChoicePublic]
    # Включена ли настоящая модель. С заглушкой выбор сохраняется и
    # заработает, когда провайдер включат, — и сказать это надо прямо.
    provider_ready: bool

    # Тематика пространства; пусто — подсказок из общего словаря нет.
    subject: str | None
    subjects: list[SubjectPublic]
    # Разрешено ли площадке брать термины загруженных словарей в общий.
    share_glossary: bool
    # Критичное замечание решает не тот, кто его нашёл или исправил.
    two_person_review: bool
    # Что отдавать на смысловую сверку.
    semantic_scope: QAScope
    # Когда исправление попадает в память переводов.
    memory_publish_on: MemoryPublish


class WorkspaceSettingsUpdate(BaseModel):
    """Правка настроек. Присылается только то, что меняется.

    «Не прислано» и «прислано пустым» различаются: первое оставляет как
    есть, второе возвращает модель к умолчанию площадки или снимает
    тематику.
    """

    translation_model: str | None = Field(default=None, max_length=120)
    subject: str | None = Field(default=None, max_length=60)
    share_glossary: bool | None = None
    two_person_review: bool | None = None
    semantic_scope: QAScope | None = None
    memory_publish_on: MemoryPublish | None = None
