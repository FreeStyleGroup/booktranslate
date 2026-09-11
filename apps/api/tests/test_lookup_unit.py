"""Разбор ответа внешнего поиска.

Проверяется то, что решает судьбу справки: выдумка не выдаётся за находку,
источник без адреса не считается источником, а незавершённый поиск
доводится до конца, а не отдаётся половиной.
"""

import json
from typing import Any

import pytest

from app.models.memory import GlossaryEntryKind
from app.services.providers import (
    ClaudeLookup,
    LookupRequest,
    LookupSettings,
    OfflineLookup,
    ProviderError,
)
from app.services.providers.lookup import build_question

ANSWER = {
    "found": True,
    "target": "базисный риск",
    "definition": "Риск расхождения цены базового актива и фьючерса.",
    "expansion": None,
    "kind": "term",
    "sources": [{"title": "Справочник", "url": "https://example.org/basis-risk"}],
}


class Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class ServerToolUse:
    def __init__(self, searches: int) -> None:
        self.web_search_requests = searches


class Usage:
    def __init__(self, searches: int = 0) -> None:
        self.input_tokens = 900
        self.output_tokens = 120
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0
        self.server_tool_use = ServerToolUse(searches)


class Message:
    def __init__(self, text: str, *, stop_reason: str = "end_turn", searches: int = 1) -> None:
        self.content = [Block(text)]
        self.stop_reason = stop_reason
        self.usage = Usage(searches)


class FakeClient:
    """Клиент, отдающий заготовленные ответы по очереди."""

    def __init__(self, *answers: Message) -> None:
        self._answers = list(answers)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **payload: Any) -> Message:
        self.calls.append(payload)

        return self._answers.pop(0)


def provider(*answers: Message) -> tuple[ClaudeLookup, FakeClient]:
    client = FakeClient(*answers)

    return ClaudeLookup(client, LookupSettings(model="claude-opus-5")), client


def request(term: str = "basis risk") -> LookupRequest:
    return LookupRequest(source_term=term, source_language="en", target_language="ru")


async def test_answer_becomes_an_explanation() -> None:
    lookup, _ = provider(Message(json.dumps(ANSWER, ensure_ascii=False)))

    explanation = await lookup.lookup(request())

    assert explanation.found is True
    assert explanation.suggested_target == "базисный риск"
    assert explanation.kind is GlossaryEntryKind.TERM
    assert explanation.references[0].url == "https://example.org/basis-risk"
    assert explanation.usage.input_tokens == 900
    # Поисковые запросы оплачиваются отдельно от токенов: не посчитать их
    # значит занизить стоимость наполнения каталога.
    assert explanation.searches == 1


async def test_json_in_a_frame_is_still_json() -> None:
    """Рамка из ```json дешевле повторного запроса."""
    raw = "Вот что удалось найти:\n```json\n" + json.dumps(ANSWER) + "\n```"
    lookup, _ = provider(Message(raw))

    explanation = await lookup.lookup(request())

    assert explanation.suggested_target == "базисный риск"


async def test_not_found_is_an_answer() -> None:
    lookup, _ = provider(Message(json.dumps({"found": False, "definition": "нет в источниках"})))

    explanation = await lookup.lookup(request())

    assert explanation.found is False
    assert explanation.definition == "нет в источниках"


async def test_found_without_translation_counts_as_not_found() -> None:
    """Полусправка, записанная как удачная, второй раз уже не запросится."""
    lookup, _ = provider(Message(json.dumps({"found": True, "definition": "что-то про риск"})))

    explanation = await lookup.lookup(request())

    assert explanation.found is False


async def test_source_without_address_is_not_a_source() -> None:
    """Непроверяемый источник — это мнение, а спор о термине им не закрыть."""
    answer = {**ANSWER, "sources": [{"title": "Из головы"}, ANSWER["sources"][0]]}
    lookup, _ = provider(Message(json.dumps(answer, ensure_ascii=False)))

    explanation = await lookup.lookup(request())

    assert len(explanation.references) == 1


async def test_unknown_kind_falls_back_to_term() -> None:
    lookup, _ = provider(Message(json.dumps({**ANSWER, "kind": "жаргонизм"}, ensure_ascii=False)))

    explanation = await lookup.lookup(request())

    assert explanation.kind is GlossaryEntryKind.TERM


async def test_abbreviation_keeps_its_expansion() -> None:
    answer = {
        **ANSWER,
        "kind": "abbreviation",
        "target": "ПЛК",
        "expansion": "programmable logic controller",
    }
    lookup, _ = provider(Message(json.dumps(answer, ensure_ascii=False)))

    explanation = await lookup.lookup(request("PLC"))

    assert explanation.kind is GlossaryEntryKind.ABBREVIATION
    assert explanation.expansion == "programmable logic controller"


async def test_paused_search_is_continued() -> None:
    """Серверный цикл инструментов упирается в свой потолок и просит продолжения."""
    lookup, client = provider(
        Message("", stop_reason="pause_turn"),
        Message(json.dumps(ANSWER, ensure_ascii=False)),
    )

    explanation = await lookup.lookup(request())

    assert explanation.found is True
    assert len(client.calls) == 2
    # Расход первой половины не выбрасывается: она оплачена так же, как
    # вторая.
    assert explanation.usage.input_tokens == 1800
    assert explanation.searches == 2


async def test_refusal_is_not_a_crash() -> None:
    """Отказ по одному термину не должен ронять прогон по списку."""
    lookup, _ = provider(Message("", stop_reason="refusal"))

    explanation = await lookup.lookup(request())

    assert explanation.found is False


async def test_answer_without_json_is_an_error() -> None:
    lookup, _ = provider(Message("Я не понял вопроса."))

    with pytest.raises(ProviderError):
        await lookup.lookup(request())


async def test_search_tools_are_attached() -> None:
    lookup, client = provider(Message(json.dumps(ANSWER, ensure_ascii=False)))

    await lookup.lookup(request())

    tools = [tool["type"] for tool in client.calls[0]["tools"]]

    assert "web_search_20260209" in tools
    # Правила одни на весь прогон по списку — за них платят один раз.
    assert client.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_question_carries_only_what_there_is() -> None:
    """Пустое поле модель читает как «отрасль не важна», а место занимает."""
    bare = build_question(request())

    assert "Предметная область" not in bare
    assert "Отрывок" not in bare

    full = build_question(
        LookupRequest(
            source_term="head",
            source_language="en",
            target_language="ru",
            sample="Pump head at rated flow.",
            subject="Насосное оборудование",
        )
    )

    assert "Насосное оборудование" in full
    assert "Pump head" in full


async def test_offline_lookup_says_so() -> None:
    """У заказчика с закрытым контуром выхода в сеть может не быть вовсе."""
    explanation = await OfflineLookup().lookup(request())

    assert explanation.found is False
    assert explanation.searches == 0


async def test_reference_with_non_web_address_is_dropped() -> None:
    """Адрес источника позже станет ссылкой в интерфейсе.

    Ответ модели — не доверенный ввод: «javascript:» в href выполнил бы чужой
    код в браузере редактора. Остаются только http и https.
    """
    answer = {
        **ANSWER,
        "sources": [
            {"title": "Скрипт", "url": "javascript:alert(1)"},
            {"title": "Файл", "url": "file:///etc/passwd"},
            {"title": "Справочник", "url": "HTTPS://example.org/basis-risk"},
        ],
    }
    lookup, _ = provider(Message(json.dumps(answer, ensure_ascii=False)))

    explanation = await lookup.lookup(request())

    assert [reference.url for reference in explanation.references] == [
        "HTTPS://example.org/basis-risk"
    ]
