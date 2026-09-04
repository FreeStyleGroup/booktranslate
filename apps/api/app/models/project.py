"""Проект перевода.

Проект — это языковая пара плюс общая для всех его документов терминология.
Руководство на восемьсот страниц приходит томами и правками; том — документ,
проект — весь комплект, и именно на его уровне держится единство терминов.
"""

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class Project(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        # Короткое имя уникально внутри организации, а не глобально: два
        # разных клиента вправе назвать проект одинаково.
        UniqueConstraint("organization_id", "slug", name="organization_slug"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Языки строками по BCP 47 («en», «ru», «de-CH»), а не перечислением:
    # список языков не должен требовать миграции базы.
    source_language: Mapped[str] = mapped_column(String(20), nullable=False)
    target_language: Mapped[str] = mapped_column(String(20), nullable=False)
