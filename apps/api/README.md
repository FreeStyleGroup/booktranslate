# API

Бэкенд платформы: FastAPI, SQLAlchemy 2 (async), Postgres, миграции Alembic.

## Запуск

Через Docker — так же, как он поедет на сервере:

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
docker compose exec api ruff format --check .
docker compose exec api mypy app tests
docker compose exec api pytest
```

Те же проверки идут локально, без контейнера (`pip install -e ".[dev]"`).
Тесты, которым нужна база, при этом пропускаются — они смотрят на
`DATABASE_URL` и без него не запускаются. В CI переменная задана, и они
выполняются по-настоящему, на Postgres.

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
  core/            настройки из окружения, пароли и токены
  db/              базовый класс моделей, движок, сессии
  models/          доменные модели
  schemas/         что приходит и уходит по HTTP
  services/        логика: доступ, проекты, документы, хранилище, форматы
  api/             зависимости, перевод ошибок в коды, обработчики
alembic/           миграции
tests/             тесты
```

Обработчик тонкий: разбирает запрос, зовёт сервис, отдаёт схему. Логика — в
`services`, и ни один из них не знает про FastAPI: сервис должно быть можно
вызвать из фоновой задачи или консольной команды.

Сервисы, работающие с данными организации, наследуют `TenantService` и
строят выборки методом `scoped` — он сам добавляет условие по организации.
Голый `select(...)` по доменной таблице в сервисе — ошибка.

Модель данных и обоснования — в `docs/DATA_MODEL.md` в корне репозитория.
