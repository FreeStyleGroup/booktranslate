"""Память переводов и глоссарий

Revision ID: 0004_memory_and_glossary
Revises: 0003_document_intake
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_memory_and_glossary"
down_revision: str | None = "0003_document_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "translation_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_language", sa.String(length=10), nullable=False),
        sa.Column("target_language", sa.String(length=10), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("target_text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=120), nullable=False, server_default="machine"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_translation_units_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_language",
            "target_language",
            "source_hash",
            name="translation_unit_source",
        ),
    )
    op.create_index(
        "ix_translation_units_organization_id", "translation_units", ["organization_id"]
    )

    op.create_table(
        "glossary_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_language", sa.String(length=10), nullable=False),
        sa.Column("target_language", sa.String(length=10), nullable=False),
        sa.Column("source_term", sa.String(length=300), nullable=False),
        sa.Column("source_term_normalized", sa.String(length=300), nullable=False),
        sa.Column("target_term", sa.String(length=300), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        # Происхождение термина: «manual», «extracted», «import:<источник>».
        # Заведено до того, как импорт написан: без него загруженную пачку не
        # обновить и не снять, не задев термины, которые правил человек.
        sa.Column("source", sa.String(length=120), nullable=False, server_default="manual"),
        # Вид записи. Аббревиатуры и непереводимое ведут себя иначе и при
        # подсказке модели, и при проверке результата.
        # Значения перечисления — ИМЕНА членов заглавными, как у остальных
        # перечислений схемы: SQLAlchemy по умолчанию пишет в базу `.name`,
        # а не `.value`, и тип, созданный по значениям, отверг бы вставку.
        sa.Column(
            "kind",
            sa.Enum("TERM", "ABBREVIATION", "DO_NOT_TRANSLATE", name="glossary_entry_kind"),
            nullable=False,
            server_default="TERM",
        ),
        # Регистр значим у аббревиатур: иначе «ИТ» найдётся внутри любого слова.
        sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_glossary_terms_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_glossary_terms_project_id_projects",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_glossary_terms_organization_id", "glossary_terms", ["organization_id"])
    op.create_index("ix_glossary_terms_project_id", "glossary_terms", ["project_id"])
    op.create_index(
        "ix_glossary_terms_source_term_normalized", "glossary_terms", ["source_term_normalized"]
    )
    op.create_index("ix_glossary_terms_source", "glossary_terms", ["source"])
    op.create_index("ix_glossary_terms_kind", "glossary_terms", ["kind"])

    # Два частичных индекса вместо одного общего: NULL в project_id означает
    # «термин всей организации», а Postgres считает NULL в уникальном индексе
    # разными значениями и пропустил бы сколько угодно копий такого термина.
    op.create_index(
        "glossary_term_in_project",
        "glossary_terms",
        [
            "organization_id",
            "project_id",
            "source_language",
            "target_language",
            "source_term_normalized",
        ],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_index(
        "glossary_term_in_organization",
        "glossary_terms",
        ["organization_id", "source_language", "target_language", "source_term_normalized"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("glossary_terms")
    op.drop_table("translation_units")

    # Перечисление в Postgres живёт отдельно от таблицы и удаление таблицы его
    # не трогает: без этой строки повторный upgrade падал бы на «type
    # glossary_entry_kind already exists».
    sa.Enum(name="glossary_entry_kind").drop(op.get_bind(), checkfirst=True)
