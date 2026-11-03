"""Перевод моделью Claude.

Устройство запроса важнее самого вызова, и оно подчинено одному: модель
должна получить всё, что нужно для правильного перевода, и ничего сверх
того. Лишний контекст — это не только деньги, это ещё и разбавленное
внимание.

**Правила в системном сообщении, материал — в пользовательском.** Правила
одинаковы для всей книги и меняются редко, поэтому их место в кэшируемой
части запроса; сегменты, термины и соседи меняются каждый раз. Порядок
обратный обошёлся бы в полную стоимость каждого запроса.

**Ответ разбирается по схеме, а не по разметке.** Модель возвращает JSON,
форма которого задана в самом запросе, и каждый перевод несёт код части блока.
Полагаться на порядок строк в свободном тексте нельзя: пропущенная строка
сдвинет всю пачку, и сорок абзацев книги встанут не на свои места — молча,
потому что текст останется связным. Лишний, повторный или потерянный код —
отказ всей пачки, а не её части: такому ответу верить нельзя ни в чём.

**Упёршийся в потолок ответ не склеивается.** Если модель не уместила пачку
в `max_tokens` или перепутала коды, пачка делится пополам и переводится заново.
Отдать обрезанный последний абзац как готовый — тот самый случай, когда ошибку
находит читатель.

**Версия промпта записывается в каждый прогон.** Смысл правил меняется вместе с
качеством перевода, и через полгода надо уметь сказать, какие главы переведены
по прежним правилам. Поменял текст `SYSTEM_PROMPT` — подними `PROMPT_VERSION`.
"""

import json
from dataclasses import dataclass, replace
from typing import Any

from app.models.memory import FirstUseRule
from app.services.providers.base import (
    ProviderError,
    Translated,
    TranslationRequest,
    Usage,
    keys_of,
)

PROMPT_VERSION = "2026.11.1"

# Схема ответа. Код обязателен: по нему перевод возвращается на своё место, а не
# по порядку строк.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
Ты профессиональный технический переводчик. Твой перевод идёт в печать без \
пересказа и без сглаживания: читатель по нему работает с оборудованием.

Правила:

1. Переводи только текст сегмента. Соседние сегменты и заголовок раздела \
даны для понимания — переводить их не нужно и включать в ответ тоже.
2. Термины, приложенные к сегменту, обязательны к употреблению именно в \
указанной форме. Если термин помечен как непереводимый, он переносится в \
перевод дословно, включая регистр. Поле first_use у термина означает, что в \
главе он встречается впервые: expand — раскрой сокращение и дай его в скобках, \
original — после перевода дай в скобках исходную форму. Дальше по главе термин \
идёт без этого.
3. Числа, единицы измерения, обозначения, артикулы, коды стандартов и \
формулы переносятся без изменений. Разделитель дробной части приводится к \
принятому в языке перевода, само число не меняется никогда.
4. Заменители вида ⟦1⟧ обозначают формулу, код или подстановку, которых \
модель не видит и которые вернутся на место сами. Каждый заменитель из текста \
сегмента обязан быть в переводе ровно один раз и без изменений; другого места \
по смыслу он занять может, а новых заменителей появиться не может.
5. Ничего не добавляй от себя: ни пояснений, ни примечаний переводчика, ни \
раскрытия сокращений, которого нет в исходнике.
6. Ничего не выбрасывай. Если фраза в исходнике неполна или оборвана, \
переводи как есть.
7. Сохраняй регистр и роль сегмента: заголовок остаётся заголовком и не \
получает точку в конце, пункт списка — пунктом, предупреждение сохраняет \
свою резкость.

Ответ — JSON по заданной схеме: для каждого присланного сегмента ровно один \
перевод с его идентификатором id, без лишних и без пропущенных."""


_TRUNCATED = (
    "Перевод не уместился в ответ модели: администратору нужно увеличить предел ответа "
    "или уменьшить размер пачки"
)


@dataclass(slots=True)
class ClaudeSettings:
    """Настройки провайдера. Отдельно от общих — их читает только он."""

    model: str
    max_tokens: int
    effort: str | None = None
    # Запасная модель на случай отказа по правилам безопасности. Технический
    # текст изредка задевает их темы — глава про взрывозащиту, про химию,
    # про досмотровое оборудование, — и без запасного пути такая пачка
    # просто не переведётся. Отключается, если у организации нет доступа
    # к этой возможности.
    use_fallbacks: bool = True


class ClaudeProvider:
    """Перевод сегментов моделью Claude.

    Клиент принимается снаружи, а не создаётся здесь: так провайдер
    проверяется тестом без сети и без ключа, а приложение остаётся хозяином
    времени жизни соединений.
    """

    def __init__(self, client: Any, settings: ClaudeSettings) -> None:
        self._client = client
        self._settings = settings

    @property
    def name(self) -> str:
        """Имя модели, а не «claude».

        В прогоне должно остаться то, по чему через полгода видно, чем
        именно переведён этот том, — и что перепроверять после смены модели.
        """
        return self._settings.model

    async def translate(self, requests: list[TranslationRequest]) -> Translated:
        if not requests:
            return Translated(items={})

        keys = keys_of(requests)
        message = await self._ask(requests)
        stop = getattr(message, "stop_reason", None)
        usage = _usage_of(message)

        if stop == "refusal":
            raise ProviderError(self._refusal_message(message), spent=usage)

        if stop == "max_tokens":
            return await self._split(requests, usage, why=_TRUNCATED)

        try:
            return Translated(items=self._parse(_text_of(message), keys), usage=usage)
        except ProviderError as error:
            return await self._split(requests, usage, why=str(error))

    async def _split(
        self, requests: list[TranslationRequest], spent: Usage, *, why: str
    ) -> Translated:
        """Пачка не удалась целиком — перевести половинами.

        Расход неудачной попытки не выбрасывается, а прибавляется к итогу:
        обрезанный ответ оплачен так же, как удачный, и отчёт, в котором его
        нет, занижает стоимость книги.

        Один сегмент разделить уже нельзя: значит, потолок ответа меньше,
        чем нужно этому абзацу, и молчать об этом нельзя — обрезанный
        перевод выглядит законченным.
        """
        if len(requests) == 1:
            raise ProviderError(why, spent=spent)

        middle = len(requests) // 2

        # Куски нумеруются заново внутри половины, поэтому коды надо закрепить
        # до деления: номер по порядку у половины был бы уже другим.
        keyed = [
            replace(request, key=key)
            for request, key in zip(requests, keys_of(requests), strict=True)
        ]

        try:
            head = await self.translate(keyed[:middle])
        except ProviderError as error:
            raise ProviderError(str(error), spent=spent + error.spent) from error

        try:
            tail = await self.translate(keyed[middle:])
        except ProviderError as error:
            raise ProviderError(str(error), spent=spent + head.usage + error.spent) from error

        return Translated(
            items={**head.items, **tail.items},
            usage=spent + head.usage + tail.usage,
        )

    async def _ask(self, requests: list[TranslationRequest]) -> Any:
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Правила одинаковы для всей книги: за них платят один
                    # раз, а не в каждом из сотен запросов.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": build_user_message(requests)}],
            "output_config": {"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        }

        if self._settings.effort:
            payload["output_config"]["effort"] = self._settings.effort

        if self._settings.use_fallbacks:
            payload["betas"] = ["server-side-fallback-2026-07-01"]
            payload["fallbacks"] = "default"

            return await self._client.beta.messages.create(**payload)

        return await self._client.messages.create(**payload)

    @staticmethod
    def _refusal_message(message: Any) -> str:
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None)

        return "Модель отказалась переводить эту пачку" + (
            f" (причина: {category})" if category else ""
        )

    @staticmethod
    def _parse(raw: str, keys: list[str]) -> dict[str, str]:
        """Разобрать ответ и проверить, что коды совпали с запрошенными."""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderError("Модель вернула ответ в неверном виде") from error

        items = payload.get("translations") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("В ответе модели нет списка переводов")

        wanted = set(keys)
        answers: dict[str, str] = {}

        for item in items:
            if not isinstance(item, dict):
                continue

            key = item.get("id")
            text = item.get("text")

            if not isinstance(key, str) or not isinstance(text, str):
                continue

            if key not in wanted:
                raise ProviderError(f"Модель вернула перевод неизвестного сегмента: {key}")

            if key in answers:
                raise ProviderError(f"Модель вернула сегмент дважды: {key}")

            answers[key] = text

        missing = [key for key in keys if key not in answers]
        if missing:
            raise ProviderError(
                "Модель вернула перевод не для всех сегментов; нет: " + ", ".join(missing)
            )

        return answers


def build_user_message(requests: list[TranslationRequest]) -> str:
    """Собрать материал для перевода.

    JSON, а не свободный текст: сегменты бывают многострочными, и разделить
    их разметкой в тексте — значит однажды разделить неверно. Пустые поля не
    отправляются: «контекста нет» и «контекст пуст» модель читает одинаково,
    а место в запросе они занимают разное.
    """
    first = requests[0]

    document: dict[str, Any] = {
        "source_language": first.source_language,
        "target_language": first.target_language,
        "segments": [
            _segment(key, request) for key, request in zip(keys_of(requests), requests, strict=True)
        ],
    }

    return json.dumps(document, ensure_ascii=False, indent=1)


def _segment(key: str, request: TranslationRequest) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": key,
        "kind": request.kind,
        "text": request.source_text,
    }

    if request.context.heading:
        item["section_heading"] = request.context.heading

    if request.context.before:
        item["context_before"] = list(request.context.before)

    if request.context.after:
        item["context_after"] = list(request.context.after)

    if request.terms:
        item["terms"] = [
            {
                "source": term.source,
                "target": term.target,
                "kind": term.kind.value,
                # Примечание к термину объясняет, чем этот «клапан»
                # отличается от соседнего, и без него выбор снова за
                # моделью.
                **({"note": term.note} if term.note else {}),
                **({"do_not_translate": True} if term.kind.value == "do_not_translate" else {}),
                **(
                    {"first_use": term.first_use_rule.value}
                    if term.source in request.first_use
                    and term.first_use_rule is not FirstUseRule.NONE
                    else {}
                ),
            }
            for term in request.terms
        ]

    return item


def _usage_of(message: Any) -> Usage:
    """Расход из ответа модели.

    Поля читаются мягко: отсутствие счётчика — не повод уронить перевод,
    который уже получен и оплачен.
    """
    usage = getattr(message, "usage", None)

    if usage is None:
        return Usage()

    return Usage(
        input_tokens=_number(usage, "input_tokens"),
        output_tokens=_number(usage, "output_tokens"),
        cached_input_tokens=_number(usage, "cache_read_input_tokens"),
        cache_write_tokens=_number(usage, "cache_creation_input_tokens"),
    )


def _number(source: Any, field: str) -> int:
    value = getattr(source, field, 0)

    return value if isinstance(value, int) else 0


def _text_of(message: Any) -> str:
    """Собрать текст ответа из блоков содержимого.

    Блоков может быть несколько, и не все они текст: при включённом
    размышлении первыми идут блоки размышления с пустым текстом. Брать
    `content[0]` — это получить пустую строку вместо ответа.
    """
    parts = []

    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))

    return "".join(parts).strip()
