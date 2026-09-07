"""Провайдер перевода — за интерфейсом.

Какой моделью переводить, решено не будет ещё какое-то время: выбор зависит
от требований заказчиков к данным — облачный API против собственного
развёртывания (см. `docs/DECISIONS.md`, раздел «Открыто»). Пока выбор открыт,
конвейер перевода не должен его ждать, поэтому провайдер объявлен протоколом,
а в поставке есть заглушка.

Заглушка не изображает перевод и не притворяется моделью. Она подставляет
термины глоссария и помечает результат — этого достаточно, чтобы проверить
весь конвейер (память, дедупликацию, статусы, проверки) без единого рубля и
без сетевых вызовов в CI.

Запрос идёт пачкой, а не по одному сегменту: у любого настоящего провайдера
накладные расходы на вызов сопоставимы с самим переводом короткой фразы, и
интерфейс, рассчитанный на один сегмент, пришлось бы переделывать первым же.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from app.services.glossary import Term


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


class TranslationProvider(Protocol):
    """Источник перевода: модель, сервис или заглушка."""

    @property
    def name(self) -> str:
        """Имя для записи в `translation_source` сегмента.

        По нему через полгода можно сказать, какой моделью переведён
        конкретный том, — и понять, что перепроверять после её смены.
        """
        ...

    async def translate(self, requests: list[TranslationRequest]) -> list[str]:
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

    async def translate(self, requests: list[TranslationRequest]) -> list[str]:
        return [self._one(request) for request in requests]

    @staticmethod
    def _one(request: TranslationRequest) -> str:
        text = request.source_text

        # Длинные термины впереди — иначе «клапан» подменится внутри
        # «обратного клапана» и второй термин уже не найдётся.
        for term in sorted(request.terms, key=lambda item: len(item.source), reverse=True):
            text = text.replace(term.source, term.target)

        return f"[{request.target_language}] {text}"


@lru_cache
def get_provider() -> TranslationProvider:
    """Провайдер перевода приложения.

    Функция, а не глобальный объект: так её подменяют в тестах через
    зависимости FastAPI, не трогая настройки процесса. Пока провайдер не
    выбран, возвращается заглушка — конвейер работает целиком, но ничего
    не стоит и никуда не ходит.
    """
    return StubProvider()
