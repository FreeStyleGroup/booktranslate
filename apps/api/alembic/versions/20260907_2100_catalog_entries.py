"""Каталог терминов: справки, накопленные бюро

Каталог отделён от словаря намеренно. Словарь хранит решения — как этот
заказчик называет эту вещь; каталог хранит справки — что такое `basis risk`
и откуда это известно. Справка переживает книгу и достаётся всем проектам
организации, поэтому и уникальность у неё по организации и языковой паре,
без проекта.

Revision ID: 0007_catalog_entries
Revises: 0006_document_usage
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_catalog_entries"
down_revision: str | None = "0006_document_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_language", sa.String(length=10), nullable=False),
        sa.Column("target_language", sa.String(length=10), nullable=False),
        sa.Column("source_term", sa.String(length=300), nullable=False),
        sa.Column("source_term_normalized", sa.String(length=300), nullable=False),
        # Ненайденное записывается наравне с найденным: «искали и не нашли» —
        # это тоже знание, и без него каждая книга снова пойдёт в сеть за
        # словом, которого там нет.
        sa.Column("found", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suggested_target", sa.String(length=300), nullable=True),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("expansion", sa.String(length=300), nullable=True),
        # Тип создан миграцией 0004 вместе с глоссарием; create_type=False
        # обязателен, иначе Alembic попробует создать его второй раз.
        sa.Column(
            "kind",
            postgresql.ENUM(
                "TERM",
                "ABBREVIATION",
                "DO_NOT_TRANSLATE",
                "NOTATION",
                "PROPER_NAME",
                name="glossary_entry_kind",
                create_type=False,
            ),
            nullable=False,
            server_default="TERM",
        ),
        sa.Column(
            # Не `references`: это зарезервированное слово SQL, и запрос,
            # написанный руками мимо SQLAlchemy, спотыкался бы на нём.
            "sources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("looked_up_by", sa.String(length=120), nullable=False, server_default=""),
        sa.Column(
            "checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_catalog_entries_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_language",
            "target_language",
            "source_term_normalized",
            name="catalog_entry_term",
        ),
    )
    op.create_index("ix_catalog_entries_organization_id", "catalog_entries", ["organization_id"])
    op.create_index(
        "ix_catalog_entries_source_term_normalized",
        "catalog_entries",
        ["source_term_normalized"],
    )


def downgrade() -> None:
    op.drop_table("catalog_entries")
