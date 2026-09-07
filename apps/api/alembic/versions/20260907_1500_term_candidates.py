"""Кандидаты в словарь, разряды и статусы терминов

Разряды и статусы взяты из рабочих реестров бюро, а не придуманы: в
переводческом реестре у записи всегда есть и вид («математическое
обозначение», «имя площадки»), и состояние решения («предварительно
рекомендован», «требует унификации по книге»). Без второго словарь
применяется как требование там, где спор о нём ещё идёт.

Revision ID: 0005_term_candidates
Revises: 0004_memory_and_glossary
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_term_candidates"
down_revision: str | None = "0004_memory_and_glossary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Разряды, которых не хватило: обозначения (μ, σᵤ, LT1) и имена
    # собственные (NASDAQ, Ho–Stoll). В научном тексте обозначений больше,
    # чем терминов, а ошибка в них тише всего — подменённый индекс не
    # читается как опечатка, он меняет смысл формулы.
    #
    # ALTER TYPE ... ADD VALUE в транзакции разрешён с Postgres 12, но
    # добавленное значение в той же транзакции использовать нельзя. Здесь
    # оно только объявляется, строк с ним миграция не пишет.
    op.execute("ALTER TYPE glossary_entry_kind ADD VALUE IF NOT EXISTS 'NOTATION'")
    op.execute("ALTER TYPE glossary_entry_kind ADD VALUE IF NOT EXISTS 'PROPER_NAME'")

    op.add_column("glossary_terms", sa.Column("reference", sa.Text(), nullable=True))
    op.add_column(
        "glossary_terms",
        sa.Column("expand_on_first_use", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Тип создаётся отдельной командой, а не самим add_column: CREATE TYPE
    # автоматически выполняется только при create_table. При добавлении
    # колонки в существующую таблицу его не будет, и миграция упадёт на
    # «type glossary_term_status does not exist».
    term_status = sa.Enum(
        "PROPOSED",
        "CONFIRMED",
        "NEEDS_REVIEW",
        "NEEDS_UNIFICATION",
        "RETIRED",
        name="glossary_term_status",
    )
    term_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "glossary_terms",
        sa.Column(
            "status",
            postgresql.ENUM(
                "PROPOSED",
                "CONFIRMED",
                "NEEDS_REVIEW",
                "NEEDS_UNIFICATION",
                "RETIRED",
                name="glossary_term_status",
                create_type=False,
            ),
            nullable=False,
            server_default="PROPOSED",
        ),
    )
    op.create_index("ix_glossary_terms_status", "glossary_terms", ["status"])

    op.create_table(
        "term_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_term", sa.String(length=300), nullable=False),
        sa.Column("source_term_normalized", sa.String(length=300), nullable=False),
        # Тип уже создан миграцией 0004 вместе с глоссарием. create_type=False
        # обязателен: без него Alembic попробует создать его второй раз и
        # миграция упадёт на «type glossary_entry_kind already exists».
        sa.Column(
            "kind",
            postgresql.ENUM(
                "TERM",
                "ABBREVIATION",
                "DO_NOT_TRANSLATE",
                name="glossary_entry_kind",
                create_type=False,
            ),
            nullable=False,
            server_default="TERM",
        ),
        # Значения перечисления — ИМЕНА членов заглавными: SQLAlchemy пишет в
        # базу `.name`, а не `.value`, и тип, созданный по значениям, отверг бы
        # вставку.
        sa.Column(
            "status",
            sa.Enum("NEW", "ACCEPTED", "REJECTED", name="term_candidate_status"),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expansion", sa.String(length=300), nullable=True),
        sa.Column("glossary_term_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_term_candidates_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_term_candidates_document_id_documents",
            ondelete="CASCADE",
        ),
        # SET NULL: удаление термина из словаря не должно стирать след того,
        # что решение по кандидату принималось.
        sa.ForeignKeyConstraint(
            ["glossary_term_id"],
            ["glossary_terms.id"],
            name="fk_term_candidates_glossary_term_id_glossary_terms",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "document_id", "source_term_normalized", name="term_candidate_in_document"
        ),
    )
    op.create_index("ix_term_candidates_organization_id", "term_candidates", ["organization_id"])
    op.create_index("ix_term_candidates_document_id", "term_candidates", ["document_id"])
    op.create_index("ix_term_candidates_status", "term_candidates", ["status"])


def downgrade() -> None:
    op.drop_table("term_candidates")

    op.drop_index("ix_glossary_terms_status", table_name="glossary_terms")
    op.drop_column("glossary_terms", "status")
    op.drop_column("glossary_terms", "expand_on_first_use")
    op.drop_column("glossary_terms", "reference")

    # Перечисления в Postgres живут отдельно от таблиц: без явного удаления
    # повторный upgrade упал бы на «type ... already exists».
    # `glossary_entry_kind` не удаляем — он принадлежит миграции 0004; её
    # откат снимет его целиком, а добавленные значения из перечисления
    # Postgres убирать не умеет в принципе.
    sa.Enum(name="term_candidate_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="glossary_term_status").drop(op.get_bind(), checkfirst=True)
