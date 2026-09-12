"""Поиск справки о термине во внешнем источнике.

Переводчик, встретивший незнакомое слово, идёт смотреть, что это такое, —
и записывает найденное, чтобы через месяц не искать заново. Здесь ровно это
и делается: слово уходит в поиск, ответ разбирается в справку, справка
ложится в каталог (`app/services/catalog.py`).

**Справка не решение.** Провайдер не заводит терминов и ничего не
подтверждает. Он приносит определение, предлагаемый перевод и адреса
источников; принимает решение человек. Разница не формальная: чужая
страница может относиться к другой отрасли, а термин, попавший в словарь без
проверки, разойдётся по всей книге и будет выглядеть согласованным.

**Ненайденное — тоже ответ.** Придуманный перевод хуже отсутствующего:
отсутствие видно, а выдумку — нет. Поэтому у справки есть `found`, и
источники обязательны там, где `found` истинно.

**Структурированный вывод здесь не используется.** Он несовместим с
цитированием, а веб-поиск снабжает ответ цитатами; запрос с обоими
отвергается целиком. Поэтому форма ответа задана в правилах, а JSON
извлекается из текста — терпимо к обрамлению, но без домысливания полей.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.memory import GlossaryEntryKind
from app.services.providers.base import ProviderError, Usage

# Версии серверных инструментов с динамической фильтрацией: модель сама
# отсеивает выдачу до того, как та попадёт в контекст. Для одного термина
# это и точнее, и дешевле, чем читать десять страниц целиком.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}
WEB_FETCH_TOOL = {"type": "web_fetch_20260209", "name": "web_fetch"}

# Сколько раз подряд разрешено продолжать серверный цикл инструментов.
# Ответ `pause_turn` означает «я ещё ищу»; без потолка редкий случай зациклит
# запрос на неопределённое время.
MAX_CONTINUATIONS = 4

SYSTEM_PROMPT = """\
Ты терминолог технического бюро переводов. Тебе дают слово или сокращение, \
встреченное в книге, и просят разобраться, что это такое и как это принято \
называть на языке перевода.

Порядок работы:

1. Найди значение в сети. Предпочитай стандарты, отраслевые справочники, \
документацию производителя и профильные издания. Форумы, машинные словари и \
пересказы — последний источник, а не первый.
2. Если это сокращение, приведи расшифровку на языке оригинала.
3. Предложи перевод, принятый в отрасли. Если термин принято не переводить \
(обозначение стандарта, торговая марка, название площадки), так и скажи.
4. Опирайся на приведённый отрывок из книги: одно и то же слово в разных \
отраслях значит разное, и справка не из той отрасли хуже её отсутствия.
5. Не нашёл — так и ответь. Придуманный перевод хуже отсутствующего: он \
попадёт в словарь и разойдётся по всей книге, выглядя согласованным.

Ответ — только JSON, без пояснений до и после, по форме:

{"found": true, "target": "перевод", "definition": "что это такое, 1-3 \
предложения", "expansion": "расшифровка сокращения на языке оригинала или \
null", "kind": "term", "sources": [{"title": "название", "url": "адрес"}]}

Разряд `kind` — одно из: term (обычный термин), abbreviation (сокращение), \
do_not_translate (не переводится), notation (математическое обозначение), \
proper_name (имя собственное).

Если не нашёл: {"found": false, "definition": "чего именно не хватило"}"""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_KINDS = {kind.value: kind for kind in GlossaryEntryKind}


@dataclass(frozen=True, slots=True)
class Reference:
    """Откуда взята справка."""

    title: str
    url: str


@dataclass(slots=True)
class LookupRequest:
    source_term: str
    source_language: str
    target_language: str

    # Отрывок из книги вокруг первого вхождения. Без него `head` — это и
    # «головка», и «оголовок», и выбор между ними делается наугад.
    sample: str = ""

    # Предметная область: название проекта или книги. Задаёт отрасль там, где
    # отрывка мало.
    subject: str | None = None


@dataclass(frozen=True, slots=True)
class Explanation:
    """Что удалось выяснить про термин."""

    found: bool
    suggested_target: str | None = None
    definition: str | None = None
    expansion: str | None = None
    kind: GlossaryEntryKind = GlossaryEntryKind.TERM
    references: tuple[Reference, ...] = ()

    usage: Usage = field(default_factory=Usage)
    # Веб-поиск оплачивается запросами, а не токенами, и в счётчиках токенов
    # его не видно вовсе.
    searches: int = 0


class TermLookupProvider(Protocol):
    """Источник справок о терминах."""

    @property
    def name(self) -> str:
        """Чем справка получена: имя модели либо «offline»."""
        ...

    async def lookup(self, request: LookupRequest) -> Explanation: ...


OFFLINE = "offline"


class OfflineLookup:
    """Поиск выключен.

    Отвечает «не нашёл» — честно и бесплатно. Нужна не ради заглушки: у
    заказчика с закрытым контуром выхода в сеть может не быть вовсе, и
    каталог тогда наполняется руками и импортом словарей, а конвейер обязан
    работать целиком.
    """

    @property
    def name(self) -> str:
        return OFFLINE

    async def lookup(self, request: LookupRequest) -> Explanation:
        return Explanation(found=False, definition="Внешний поиск выключен")


@dataclass(slots=True)
class LookupSettings:
    model: str
    max_tokens: int = 4000


class ClaudeLookup:
    """Справка от модели с выходом в сеть.

    Клиент принимается снаружи, как и у провайдера перевода: так справочник
    проверяется тестом без сети и без ключа.
    """

    def __init__(self, client: Any, settings: LookupSettings) -> None:
        self._client = client
        self._settings = settings

    @property
    def name(self) -> str:
        return self._settings.model

    async def lookup(self, request: LookupRequest) -> Explanation:
        messages: list[dict[str, Any]] = [{"role": "user", "content": build_question(request)}]
        usage = Usage()
        searches = 0

        for _ in range(MAX_CONTINUATIONS + 1):
            message = await self._ask(messages)
            usage = usage + _usage_of(message)
            searches += _searches_of(message)
            stop = getattr(message, "stop_reason", None)

            if stop == "refusal":
                return Explanation(
                    found=False,
                    definition="Модель отказалась отвечать про этот термин",
                    usage=usage,
                    searches=searches,
                )

            # Серверный цикл инструментов упёрся в свой потолок и просит
            # продолжения. Своего сообщения добавлять не нужно: продолжение
            # опознаётся по последнему блоку ответа.
            if stop == "pause_turn":
                messages.append({"role": "assistant", "content": message.content})
                continue

            return _explanation(_text_of(message), usage=usage, searches=searches)

        raise ProviderError(f"Поиск по термину «{request.source_term}» не завершился")

    async def _ask(self, messages: list[dict[str, Any]]) -> Any:
        return await self._client.messages.create(
            model=self._settings.model,
            max_tokens=self._settings.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Правила одни на весь прогон по списку кандидатов.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
            tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
        )


def build_question(request: LookupRequest) -> str:
    """Собрать вопрос о термине.

    Отрывок и предметная область идут в вопрос, только если они есть: пустое
    поле модель читает как «отрасль не важна», а место в запросе занимает.
    """
    parts = [
        f"Термин: {request.source_term}",
        f"Язык оригинала: {request.source_language}",
        f"Язык перевода: {request.target_language}",
    ]

    if request.subject:
        parts.append(f"Предметная область: {request.subject}")

    if request.sample:
        parts.append(f"Отрывок из книги: {request.sample}")

    return "\n".join(parts)


def _explanation(raw: str, *, usage: Usage, searches: int) -> Explanation:
    payload = _payload(raw)

    if not payload.get("found"):
        return Explanation(
            found=False,
            definition=_string(payload.get("definition")),
            usage=usage,
            searches=searches,
        )

    target = _string(payload.get("target"))

    # Найдено, но перевода нет — значит не найдено. Полусправка, попавшая в
    # каталог как удачная, второй раз уже не запросится.
    if target is None:
        return Explanation(
            found=False,
            definition=_string(payload.get("definition")),
            usage=usage,
            searches=searches,
        )

    return Explanation(
        found=True,
        suggested_target=target,
        definition=_string(payload.get("definition")),
        expansion=_string(payload.get("expansion")),
        kind=_KINDS.get(str(payload.get("kind", "")).lower(), GlossaryEntryKind.TERM),
        references=_references(payload.get("sources")),
        usage=usage,
        searches=searches,
    )


def _payload(raw: str) -> dict[str, Any]:
    """Достать объект JSON из ответа.

    Терпимо к обрамлению — рамка из ```json и фраза перед ответом стоят
    дешевле повторного запроса, — но не к отсутствию самого объекта.
    """
    match = _JSON_OBJECT.search(raw)

    if match is None:
        raise ProviderError("В ответе поиска нет JSON")

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ProviderError(f"Ответ поиска не разобрался как JSON: {error}") from error

    if not isinstance(payload, dict):
        raise ProviderError("Ответ поиска — не объект")

    return payload


def _references(value: Any) -> tuple[Reference, ...]:
    if not isinstance(value, list):
        return ()

    found = []

    for item in value:
        if not isinstance(item, dict):
            continue

        url = _string(item.get("url"))
        if url is None:
            # Источник без адреса непроверяем, а значит и не источник.
            continue
        # Только веб-адреса: ответ модели — не доверенный ввод, а адрес
        # позже станет ссылкой в интерфейсе. «javascript:» в href — это
        # выполнение чужого кода в браузере редактора.
        if not url.lower().startswith(("http://", "https://")):
            continue

        found.append(Reference(title=_string(item.get("title")) or url, url=url))

    return tuple(found)


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    stripped = value.strip()

    return stripped or None


def _usage_of(message: Any) -> Usage:
    usage = getattr(message, "usage", None)

    if usage is None:
        return Usage()

    return Usage(
        input_tokens=_number(usage, "input_tokens"),
        output_tokens=_number(usage, "output_tokens"),
        cached_input_tokens=_number(usage, "cache_read_input_tokens"),
        cache_write_tokens=_number(usage, "cache_creation_input_tokens"),
    )


def _searches_of(message: Any) -> int:
    """Сколько поисковых запросов сделано.

    Они оплачиваются отдельно от токенов, и в счётчиках токенов их не видно:
    отчёт без них занижал бы стоимость наполнения каталога.
    """
    usage = getattr(message, "usage", None)
    server = getattr(usage, "server_tool_use", None)

    return _number(server, "web_search_requests") if server is not None else 0


def _number(source: Any, field_name: str) -> int:
    value = getattr(source, field_name, 0)

    return value if isinstance(value, int) else 0


def _text_of(message: Any) -> str:
    parts = []

    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))

    return "".join(parts).strip()
