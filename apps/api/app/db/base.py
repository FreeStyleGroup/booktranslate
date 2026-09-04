"""Базовый класс моделей и общие соглашения схемы."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Явные имена ограничений и индексов. Без них Postgres придумывает имена сам,
# Alembic в следующей миграции не находит нужное ограничение по имени, и
# откат превращается в ручную работу с боевой базой.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
