# Python 3.12: локальный на машине разработчика — 3.9, и типовые
# аннотации вроде «str | None» там не работают. Версия среды закреплена
# здесь, а не в инструкции по установке.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Зависимости ставятся до копирования кода: слой с ними переиспользуется,
# пока не изменится pyproject, и правка одного файла не тянет полную
# переустановку пакетов.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY . .

# Работа не от root. Внутри контейнера разбираются чужие DOCX, EPUB и
# термбазы — файлы, которые прислал кто угодно; ошибка разбора под нулевым
# идентификатором отдаёт нападающему весь контейнер. Каталог хранилища
# заводится здесь же: том монтируется с правами хозяина, и без явного
# владельца приложение не сможет в него писать.
RUN useradd --system --uid 1000 --create-home app \
    && mkdir -p /var/booktranslate/storage \
    && chown -R app:app /app /var/booktranslate

USER app

EXPOSE 8000

# Проверка живости внутри образа: оркестратор узнаёт о зависшем процессе
# сам, не дожидаясь жалоб. Запрос идёт мимо базы — её недоступность
# перезапуском не лечится.
#
# Заголовок Host обязателен. В рабочей среде API отвечает только на имена
# из ALLOWED_HOSTS, и запрос на 127.0.0.1 без него получает 400 «Invalid
# host header»: контейнер числился бы больным всю жизнь, хотя работает.
# Имя берётся из той же переменной, по которой прокси получает сертификат;
# без неё (разработка, где разрешены любые имена) — localhost.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/health', headers={'Host': os.environ.get('API_DOMAIN', 'localhost')}))"

# proxy-headers: за обратным прокси адрес соединения — это адрес прокси, и
# без разбора заголовков весь мир окажется одним клиентом для ограничителя
# частоты и одной строкой в списке сессий. Кому верить — задаётся
# переменной FORWARDED_ALLOW_IPS.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
