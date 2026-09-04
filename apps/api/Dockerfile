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

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
