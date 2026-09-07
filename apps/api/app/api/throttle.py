"""Ограничение частоты запросов.

Без него вход — оружие против самого сервера. Пароль проверяется Argon2id,
а он по замыслу дорогой: десятки одновременных запросов на `/auth/login` с
любым паролем занимают всю память и весь процессор, и API ложится целиком,
не пропустив ни одного настоящего пользователя. Тот же счётчик закрывает и
перебор паролей.

Счётчик в памяти процесса, а не в Redis, и это осознанный размен: одна
машина — один процесс, зависимостей не прибавляется, а при переезде на
несколько рабочих процессов ограничение станет мягче ровно во столько раз,
сколько их запущено. Момент, когда это перестанет годиться, виден заранее —
он наступит вместе с горизонтальным масштабированием, и тогда счётчик
переедет в общее хранилище.

Считается по адресу источника. За обратным прокси адрес соединения — это
адрес прокси, поэтому uvicorn запускается с `--proxy-headers` и списком
доверенных адресов: без этого весь мир окажется одним клиентом.
"""

import time
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

# Пути, у которых своя, строгая мера. Проверка пароля стоит дороже любого
# чтения, и мерить её общей меркой нельзя.
GUARDED_PREFIXES = ("/auth/login", "/auth/register", "/auth/refresh")

# Сколько разных источников помним. Словарь без потолка — это утечка,
# растянутая во времени: чем дольше живёт процесс, тем больше в нём мёртвых
# ключей.
MAX_KEYS = 20_000


class Window:
    """Скользящее окно попыток по ключу.

    Дек, а не счётчик с обнулением: счётчик разрешает двойную порцию на
    стыке окон, и «десять в минуту» превращается в двадцать за секунду.
    """

    def __init__(self, limit: int, seconds: float) -> None:
        self._limit = limit
        self._seconds = seconds
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allows(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]

        while hits and now - hits[0] > self._seconds:
            hits.popleft()

        if not hits:
            # Пустой дек оставлять незачем: он и есть будущая утечка.
            del self._hits[key]

            if len(self._hits) >= MAX_KEYS:
                self._forget_oldest()

            self._hits[key].append(now)
            return True

        if len(hits) >= self._limit:
            return False

        hits.append(now)
        return True

    def _forget_oldest(self) -> None:
        """Освободить место под новые ключи.

        Выбрасывается четверть самых давних: чистить по одному значит
        выполнять этот обход на каждом запросе после переполнения.
        """
        by_age = sorted(self._hits.items(), key=lambda item: item[1][0])

        for key, _ in by_age[: max(1, len(by_age) // 4)]:
            del self._hits[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Потолок на число запросов с одного адреса."""

    def __init__(self, app: object, *, general: int, guarded: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._general = Window(general, 60.0)
        self._guarded = Window(guarded, 60.0)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        source = request.client.host if request.client else "unknown"
        path = request.url.path

        window = self._guarded if path.startswith(GUARDED_PREFIXES) else self._general

        if not window.allows(source):
            # 429 с указанием, когда пробовать снова: клиент, который умеет
            # ждать, должен знать сколько.
            return JSONResponse(
                {"detail": "Слишком много запросов. Повторите через минуту."},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
