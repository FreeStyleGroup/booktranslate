"""Провайдер перевода моделью — без сети и без ключа.

Проверяется то, что нельзя проверить на живом вызове дёшево и повторяемо:
что в запрос уходит ровно нужное, что ответ возвращается на свои места по
номерам, а не по порядку строк, и что оборванный ответ не выдаётся за
готовый перевод.
"""

import json
from typing import Any

import pytest

from app.models.memory import GlossaryEntryKind
from app.services.glossary import Term
from app.services.providers import ProviderError, TranslationRequest
from app.services.providers.base import Neighbourhood
from app.services.providers.claude import ClaudeProvider, ClaudeSettings, build_user_message


class Block:
    def __init__(self, text: str, kind: str = "text") -> None:
        self.type = kind
        self.text = text


class Message:
    def __init__(self, blocks: list[Block], stop_reason: str = "end_turn") -> None:
        self.content = blocks
        self.stop_reason = stop_reason
        self.stop_details = None


class Messages:
    """Поддельный messages-эндпоинт: помнит запросы и отдаёт заготовленное."""

    def __init__(self, answers: list[Message]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    async def create(self, **payload: Any) -> Message:
        self.calls.append(payload)

        return self.answers.pop(0) if self.answers else Message([Block("{}")])


class Client:
    def __init__(self, answers: list[Message] | None = None) -> None:
        self.messages = Messages(list(answers or []))
        # Ветка с запасной моделью ходит через beta — тот же объект, чтобы
        # тест видел запросы независимо от настройки.
        self.beta = type("Beta", (), {"messages": self.messages})()


def answer(texts: list[str], stop_reason: str = "end_turn") -> Message:
    payload = {"translations": [{"id": number, "text": text} for number, text in enumerate(texts)]}

    return Message([Block(json.dumps(payload, ensure_ascii=False))], stop_reason)


def provider(client: Client, **overrides: Any) -> ClaudeProvider:
    settings = ClaudeSettings(
        model=overrides.get("model", "claude-opus-5"),
        max_tokens=overrides.get("max_tokens", 16000),
        effort=overrides.get("effort"),
        use_fallbacks=bool(overrides.get("use_fallbacks", False)),
    )

    return ClaudeProvider(client, settings)


def request(text: str, **kwargs: Any) -> TranslationRequest:
    return TranslationRequest(
        source_text=text,
        source_language="en",
        target_language="ru",
        terms=list(kwargs.get("terms", [])),
        kind=str(kwargs.get("kind", "paragraph")),
        context=kwargs.get("context", Neighbourhood()),
    )


async def test_translations_return_in_order_of_request() -> None:
    """Ответ раскладывается по номерам: порядок строк в JSON ничего не решает."""
    payload = {
        "translations": [
            {"id": 1, "text": "второй"},
            {"id": 0, "text": "первый"},
        ]
    }
    client = Client([Message([Block(json.dumps(payload, ensure_ascii=False))])])

    result = await provider(client).translate([request("first"), request("second")])

    assert result.texts == ["первый", "второй"]


async def test_missing_translation_is_an_error() -> None:
    """Пропущенный сегмент сдвинул бы всю пачку — и текст остался бы связным."""
    payload = {"translations": [{"id": 0, "text": "первый"}]}
    client = Client([Message([Block(json.dumps(payload, ensure_ascii=False))])])

    with pytest.raises(ProviderError, match="не для всех"):
        await provider(client).translate([request("first"), request("second")])


async def test_thinking_blocks_do_not_hide_the_answer() -> None:
    """При включённом размышлении первый блок ответа — не текст."""
    payload = {"translations": [{"id": 0, "text": "первый"}]}
    client = Client(
        [
            Message(
                [Block("", "thinking"), Block(json.dumps(payload, ensure_ascii=False))],
            )
        ]
    )

    assert (await provider(client).translate([request("first")])).texts == ["первый"]


async def test_truncated_batch_is_split_in_half() -> None:
    """Обрезанный ответ не склеивается: пачка переводится половинами."""
    client = Client(
        [
            answer(["", ""], stop_reason="max_tokens"),
            answer(["первый"]),
            answer(["второй"]),
        ]
    )

    result = await provider(client).translate([request("first"), request("second")])

    assert result.texts == ["первый", "второй"]
    assert len(client.messages.calls) == 3


async def test_single_segment_that_does_not_fit_is_reported() -> None:
    """Делить дальше нечего — молчать об этом нельзя."""
    client = Client([answer([""], stop_reason="max_tokens")])

    with pytest.raises(ProviderError, match="не уместился"):
        await provider(client).translate([request("first")])


async def test_refusal_is_reported_with_reason() -> None:
    message = answer([""], stop_reason="refusal")
    message.stop_details = type("Details", (), {"category": "cyber"})()
    client = Client([message])

    with pytest.raises(ProviderError, match="cyber"):
        await provider(client).translate([request("first")])


async def test_broken_json_is_reported() -> None:
    client = Client([Message([Block("вот вам перевод")])])

    with pytest.raises(ProviderError, match="JSON"):
        await provider(client).translate([request("first")])


async def test_rules_are_cached_and_material_is_not() -> None:
    """Правила одинаковы для всей книги — за них платят один раз."""
    client = Client([answer(["первый"])])

    await provider(client).translate([request("first")])
    payload = client.messages.calls[0]

    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["model"] == "claude-opus-5"
    assert payload["output_config"]["format"]["type"] == "json_schema"
    # Материал уходит пользовательским сообщением, а не в правила: иначе
    # кэш обнулялся бы на каждой пачке.
    assert "first" not in json.dumps(payload["system"], ensure_ascii=False)


async def test_fallbacks_go_through_beta_endpoint() -> None:
    client = Client([answer(["первый"])])

    await provider(client, use_fallbacks=True).translate([request("first")])
    payload = client.messages.calls[0]

    assert payload["fallbacks"] == "default"
    assert payload["betas"] == ["server-side-fallback-2026-07-01"]


async def test_usage_comes_back_with_the_translation() -> None:
    """Без этого книгу переводят вслепую и узнают цену из счёта."""
    message = answer(["первый"])
    message.usage = type(
        "Usage",
        (),
        {
            "input_tokens": 120,
            "output_tokens": 45,
            "cache_read_input_tokens": 900,
            "cache_creation_input_tokens": 30,
        },
    )()

    result = await provider(Client([message])).translate([request("first")])

    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 45
    assert result.usage.cached_input_tokens == 900
    assert result.usage.cache_write_tokens == 30


async def test_usage_of_a_truncated_attempt_is_not_lost() -> None:
    """Обрезанный ответ оплачен так же, как удачный."""

    def spent(tokens: int) -> Any:
        return type("Usage", (), {"input_tokens": tokens, "output_tokens": 0})()

    first = answer(["", ""], stop_reason="max_tokens")
    first.usage = spent(100)

    head = answer(["первый"])
    head.usage = spent(10)

    tail = answer(["второй"])
    tail.usage = spent(20)

    result = await provider(Client([first, head, tail])).translate(
        [request("first"), request("second")]
    )

    assert result.usage.input_tokens == 130


async def test_missing_usage_does_not_break_the_translation() -> None:
    """Отсутствие счётчика — не повод потерять уже оплаченный перевод."""
    result = await provider(Client([answer(["первый"])])).translate([request("first")])

    assert result.texts == ["первый"]
    assert result.usage.input_tokens == 0


async def test_provider_name_is_the_model() -> None:
    """В сегменте должно остаться, чем именно переведён этот том."""
    assert provider(Client(), model="claude-opus-5").name == "claude-opus-5"


def test_message_carries_context_and_terms() -> None:
    term = Term(
        source="check valve",
        target="обратный клапан",
        mandatory=True,
        note="запорная арматура",
        kind=GlossaryEntryKind.TERM,
    )

    body = json.loads(
        build_user_message(
            [
                request(
                    "Open the check valve.",
                    kind="warning",
                    terms=[term],
                    context=Neighbourhood(
                        before=("Before start.",), after=("Then wait.",), heading="Safety"
                    ),
                )
            ]
        )
    )

    segment = body["segments"][0]

    assert body["source_language"] == "en"
    assert segment["id"] == 0
    assert segment["kind"] == "warning"
    assert segment["section_heading"] == "Safety"
    assert segment["context_before"] == ["Before start."]
    assert segment["context_after"] == ["Then wait."]
    assert segment["terms"][0]["target"] == "обратный клапан"
    assert segment["terms"][0]["note"] == "запорная арматура"


def test_empty_context_is_not_sent() -> None:
    """«Контекста нет» и «контекст пуст» модель читает одинаково, а платят за них по-разному."""
    segment = json.loads(build_user_message([request("Open the valve.")]))["segments"][0]

    assert "context_before" not in segment
    assert "context_after" not in segment
    assert "section_heading" not in segment
    assert "terms" not in segment


def test_do_not_translate_is_marked() -> None:
    term = Term(
        source="USB",
        target="USB",
        mandatory=True,
        note=None,
        kind=GlossaryEntryKind.DO_NOT_TRANSLATE,
    )

    segment = json.loads(build_user_message([request("Connect USB.", terms=[term])]))["segments"][0]

    assert segment["terms"][0]["do_not_translate"] is True
