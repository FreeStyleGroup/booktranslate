# API

Бэкенд платформы: FastAPI, SQLAlchemy 2 (async), Postgres, миграции Alembic.

## Запуск

Через Docker — так же, как он поедет на сервере, и без зависимости от версии
Python на машине разработчика (локально стоит 3.9, коду нужен 3.12):

```bash
# из корня репозитория
docker compose up --build          # база + API на http://localhost:8000
docker compose exec api alembic upgrade head   # накатить схему
```

Проверка, что живо:

```
GET http://localhost:8000/health         процесс отвечает
GET http://localhost:8000/health/ready   база доступна
GET http://localhost:8000/docs           схема OpenAPI
```

## Проверки

```bash
docker compose exec api ruff check .
docker compose exec api mypy app
docker compose exec api pytest
```

## Миграции

Схема меняется только миграциями — правки таблиц руками не переживают
следующий разворот базы.

```bash
docker compose exec api alembic revision --autogenerate -m "что меняем"
docker compose exec api alembic upgrade head
docker compose exec api alembic downgrade -1     # откат одной ревизии
```

Новую модель нужно добавить в `app/models/__init__.py`, иначе autogenerate
её не увидит и молча сгенерирует пустую миграцию.

## Устройство

```
app/
  main.py          сборка приложения
  core/config.py   настройки из окружения
  db/              базовый класс моделей, движок, сессии
  models/          доменные модели
  api/routes/      обработчики
alembic/           миграции
tests/             тесты
```

Модель данных и обоснования — в `docs/DATA_MODEL.md` в корне репозитория.
