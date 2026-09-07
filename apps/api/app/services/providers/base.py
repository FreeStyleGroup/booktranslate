"""Договор с провайдером перевода и заглушка.

Провайдер объявлен протоколом, а не классом: какой моделью переводить,
зависит от требований заказчика к данным (облачный API против собственного
развёртывания), и конвейер не должен ждать этого решения.

Заглушка не изображает перевод и не притворяется моделью. Она подставляет
термины глоссария и помечает результат — этого достаточно, чтобы проверить
весь конвейер (память, дедупликацию, контекст, статусы, проверки) без единого
рубля и без сетевых вызовов в CI.

Запрос идёт пачкой, а не по одному сегменту: у любого настоящего провайдера
накладные расходы на вызов сопоставимы с самим переводом короткой фразы, и
интерфейс, рассчитанный на один сегмент, пришлось бы переделывать первым же.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.services.glossary import Term


class ProviderError(Exception):
    """Провайдер не смог перевести пачку.

    Отдельный тип, а не общая ошибка: сбой модели — это не ошибка данных и
    не ошибка пользователя, и обходиться с ним надо иначе.
    """


@dataclass(frozen=True, slots=True)
class Neighbourhood:
    """Окружение сегмента в документе.

    Сегмент, отданный модели в одиночку, переводится наугад везде, где смысл
    держится на соседях: «он», «указанный выше», «то же самое», опущенное
    подлежащее. Модель при этом не сомневается — она выдаёт гладкую фразу,
    в которой местоимение указывает не туда, и заметить это можно только
    рядом с исходником.

    Заголовок раздела идёт отдельно от соседей: он задаёт предметную
    область на десятки сегментов вперёд, а `bank` в главе про гидравлику и
    в главе про финансы — разные слова.
    """

    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    heading: str | None = None


EMPTY_CONTEXT = Neighbourhood()


@dataclass(slots=True)
class TranslationRequest:
    source_text: str
    source_language: str
    target_language: str

    # Термины, встретившиеся именно в этом сегменте. В запрос уходят только
    # они, а не весь словарь: словарь на тысячу строк в каждом запросе — это
    # оплаченный контекст, который к тексту отношения не имеет.
    terms: list[Term] = field(default_factory=list)

    # Роль сегмента в документе: у заголовка свои требования к краткости,
    # у предупреждения цена ошибки выше всего.
    kind: str = "paragraph"

    # Соседние сегменты и заголовок раздела. Переводу не подлежат — они
    # нужны модели, чтобы понять, к чему относится «он» и о чём вообще речь.
    context: Neighbourhood = EMPTY_CONTEXT


@dataclass(frozen=True, slots=True)
class Usage:
    """Сколько стоил вызов — в токенах, а не в деньгах.

    Деньги считаются отдельно и по прейскуранту: цены меняются, а токены,
    потраченные на эту книгу, — исторический факт, и пересчитывать его
    задним числом нельзя.

    Прочитанное из кэша учитывается отдельно от обычного ввода: оно стоит
    примерно десятую часть, и складывать их в одно число значит потерять
    ровно то, ради чего кэш заводили.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    # Записанное в кэш: дороже обычного ввода, но платится один раз.
    cache_write_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True, slots=True)
class Translated:
    """Ответ провайдера: переводы и цена вопроса.

    Расход возвращается вместе с переводом, а не собирается провайдером у
    себя: провайдер один на процесс и обслуживает несколько переводов
    сразу, и счётчик внутри него смешал бы чужие книги.
    """

    texts: list[str]
    usage: Usage = Usage()


class TranslationProvider(Protocol):
    """Источник перевода: модель, сервис или заглушка."""

    @property
    def name(self) -> str:
        """Имя для записи в `translation_source` сегмента.

        По нему через полгода можно сказать, какой моделью переведён
        конкретный том, — и понять, что перепроверять после её смены.
        """
        ...

    async def translate(self, requests: list[TranslationRequest]) -> Translated:
        """Перевести пачку. Порядок ответов совпадает с порядком запросов."""
        ...


class StubProvider:
    """Заглушка для разработки и тестов.

    Подставляет термины глоссария и помечает текст меткой языка. Это не
    перевод и не выдаёт себя за него: метка нужна, чтобы в тестах и в
    интерфейсе разработчика было сразу видно, что модель не подключена.
    """

    @property
    def name(self) -> str:
        return "stub"

    async def translate(self, requests: list[TranslationRequest]) -> Translated:
        # Расход нулевой, и это не заглушка ради заглушки: заглушка ничего
        # не тратит, и показывать иное было бы враньём в отчёте.
        return Translated(texts=[self._one(request) for request in requests])

    @staticmethod
    def _one(request: TranslationRequest) -> str:
        text = request.source_text

        # Длинные термины впереди — иначе «клапан» подменится внутри
        # «обратного клапана» и второй термин уже не найдётся.
        for term in sorted(request.terms, key=lambda item: len(item.source), reverse=True):
            text = text.replace(term.source, term.target)

        return f"[{request.target_language}] {text}"
