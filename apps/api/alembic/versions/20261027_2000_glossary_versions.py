"""Версии глоссария, кандидаты по главам, правило первого употребления

Перевод опирается на утверждённую версию глоссария — неизменяемый снимок
терминов с номером и решением, а не на живой словарь. Рядом со снимком —
отличия обязательных терминов от предыдущей утверждённой версии и блоки
книги, которые эти отличия задевают.

У термина появляются допустимые варианты перевода, предметная область и
правило первого употребления — перечислением вместо флажка «раскрывать»:
сокращение раскрывают, а термину без устоявшегося названия дают оригинал.
Прежний флажок переезжает в «раскрыть сокращение».

Кандидаты в словарь собираются по главе. Проход по документу остаётся,
пока жив прежний контур, — у кандидата ровно один владелец. Каждый проход
по главе записывается: «кандидатов нет» без записи не отличить от «прохода
не было».

Revision ID: 0016_glossary_versions
Revises: 0015_book_objects
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_glossary_versions"
down_revision: str | None = "0015_book_objects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _tenant(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    # Значение не используется в этой же транзакции — так Postgres 12+
    # разрешает пополнять перечисление внутри неё.
    op.execute("ALTER TYPE code_kind ADD VALUE 'GLOSSARY_VERSION' AFTER 'ISSUE'")

    _upgrade_terms()
    _upgrade_candidates()
    _create_passes()
    _create_versions()


def _upgrade_terms() -> None:
    op.add_column(
        "glossary_terms",
        sa.Column(
            "allowed_variants",
            postgresql.ARRAY(sa.String(length=300)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.alter_column("glossary_terms", "allowed_variants", server_default=None)
    op.add_column("glossary_terms", sa.Column("domain", sa.String(length=120), nullable=True))

    rule = sa.Enum("NONE", "EXPAND", "ORIGINAL", name="first_use_rule")
    rule.create(op.get_bind())
    op.add_column(
        "glossary_terms",
        sa.Column("first_use_rule", rule, nullable=False, server_default="NONE"),
    )
    op.execute(
        "UPDATE glossary_terms SET first_use_rule = 'EXPAND' WHERE expand_on_first_use IS TRUE"
    )
    op.alter_column("glossary_terms", "first_use_rule", server_default=None)
    op.drop_column("glossary_terms", "expand_on_first_use")


def _upgrade_candidates() -> None:
    op.alter_column("term_candidates", "document_id", nullable=True)
    op.add_column(
        "term_candidates",
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "term_candidates",
        sa.Column("first_block_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_term_candidates_chapter_id_chapters"),
        "term_candidates",
        "chapters",
        ["chapter_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_term_candidates_first_block_id_blocks"),
        "term_candidates",
        "blocks",
        ["first_block_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_term_candidates_chapter_id"), "term_candidates", ["chapter_id"])
    op.create_unique_constraint(
        "term_candidate_in_chapter", "term_candidates", ["chapter_id", "source_term_normalized"]
    )
    op.create_check_constraint(
        op.f("ck_term_candidates_term_candidate_owner"),
        "term_candidates",
        "num_nonnulls(document_id, chapter_id) = 1",
    )


def _create_passes() -> None:
    op.create_table(
        "terminology_passes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("master_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("min_frequency", sa.Integer(), nullable=False),
        sa.Column("found", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_terminology_passes_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_terminology_passes_chapter_id_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["chapter_masters.id"],
            name=op.f("fk_terminology_passes_master_id_chapter_masters"),
            ondelete="CASCADE",
        ),
        _tenant("terminology_passes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_passes")),
    )
    for column in ("chapter_id", "master_id", "organization_id"):
        op.create_index(op.f(f"ix_terminology_passes_{column}"), "terminology_passes", [column])


def _create_versions() -> None:
    op.create_table(
        "glossary_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "APPROVED", "SUPERSEDED", name="glossary_version_status"),
            nullable=False,
        ),
        sa.Column("base_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("term_count", sa.Integer(), nullable=False),
        sa.Column("basis", postgresql.JSONB(), nullable=False),
        sa.Column("empty_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_glossary_versions_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["base_id"],
            ["glossary_versions.id"],
            name=op.f("fk_glossary_versions_base_id_glossary_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["book_editions.id"],
            name=op.f("fk_glossary_versions_book_id_book_editions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_glossary_versions_chapter_id_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_glossary_versions_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["glossary_versions.id"],
            name=op.f("fk_glossary_versions_superseded_by_id_glossary_versions"),
            ondelete="SET NULL",
        ),
        _tenant("glossary_versions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_glossary_versions")),
        sa.UniqueConstraint("book_id", "number", name="glossary_version_number"),
    )
    for column in ("book_id", "chapter_id", "organization_id"):
        op.create_index(op.f(f"ix_glossary_versions_{column}"), "glossary_versions", [column])

    # Одна версия каждого состояния на область. Книжная версия — пустая
    # глава, и пустые здесь равны друг другу: иначе книжных черновиков
    # можно было бы завести сколько угодно.
    for name, status in (("one_draft", "DRAFT"), ("one_approved", "APPROVED")):
        op.create_index(
            f"glossary_version_{name}",
            "glossary_versions",
            ["book_id", "chapter_id"],
            unique=True,
            postgresql_where=sa.text(f"status = '{status}'"),
            postgresql_nulls_not_distinct=True,
        )

    op.create_table(
        "glossary_version_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_term", sa.String(length=300), nullable=False),
        sa.Column("source_term_normalized", sa.String(length=300), nullable=False),
        sa.Column("target_term", sa.String(length=300), nullable=False),
        sa.Column("allowed_variants", postgresql.ARRAY(sa.String(length=300)), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="glossary_entry_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="glossary_term_status", create_type=False),
            nullable=False,
        ),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column(
            "first_use_rule",
            postgresql.ENUM(name="first_use_rule", create_type=False),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["glossary_terms.id"],
            name=op.f("fk_glossary_version_terms_term_id_glossary_terms"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["glossary_versions.id"],
            name=op.f("fk_glossary_version_terms_version_id_glossary_versions"),
            ondelete="CASCADE",
        ),
        _tenant("glossary_version_terms"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_glossary_version_terms")),
        sa.UniqueConstraint(
            "version_id", "source_term_normalized", name="glossary_version_term_source"
        ),
    )
    for column in ("version_id", "organization_id"):
        op.create_index(
            op.f(f"ix_glossary_version_terms_{column}"), "glossary_version_terms", [column]
        )

    op.create_table(
        "glossary_version_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_term", sa.String(length=300), nullable=False),
        sa.Column("source_term_normalized", sa.String(length=300), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("ADDED", "CHANGED", "REMOVED", name="term_change_kind"),
            nullable=False,
        ),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["glossary_versions.id"],
            name=op.f("fk_glossary_version_changes_version_id_glossary_versions"),
            ondelete="CASCADE",
        ),
        _tenant("glossary_version_changes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_glossary_version_changes")),
        sa.UniqueConstraint(
            "version_id", "source_term_normalized", name="glossary_version_change_source"
        ),
    )
    for column in ("version_id", "organization_id"):
        op.create_index(
            op.f(f"ix_glossary_version_changes_{column}"), "glossary_version_changes", [column]
        )

    op.create_table(
        "glossary_version_impacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name=op.f("fk_glossary_version_impacts_block_id_blocks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["change_id"],
            ["glossary_version_changes.id"],
            name=op.f("fk_glossary_version_impacts_change_id_glossary_version_changes"),
            ondelete="CASCADE",
        ),
        _tenant("glossary_version_impacts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_glossary_version_impacts")),
        sa.UniqueConstraint("change_id", "block_id", name="glossary_version_impact_block"),
    )
    for column in ("change_id", "block_id", "organization_id"):
        op.create_index(
            op.f(f"ix_glossary_version_impacts_{column}"), "glossary_version_impacts", [column]
        )


def downgrade() -> None:
    for table, columns in (
        ("glossary_version_impacts", ("change_id", "block_id", "organization_id")),
        ("glossary_version_changes", ("version_id", "organization_id")),
        ("glossary_version_terms", ("version_id", "organization_id")),
    ):
        for column in columns:
            op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
        op.drop_table(table)
    sa.Enum(name="term_change_kind").drop(op.get_bind(), checkfirst=True)

    for name in ("one_draft", "one_approved"):
        op.drop_index(f"glossary_version_{name}", table_name="glossary_versions")
    for column in ("book_id", "chapter_id", "organization_id"):
        op.drop_index(op.f(f"ix_glossary_versions_{column}"), table_name="glossary_versions")
    op.drop_table("glossary_versions")
    sa.Enum(name="glossary_version_status").drop(op.get_bind(), checkfirst=True)

    for column in ("chapter_id", "master_id", "organization_id"):
        op.drop_index(op.f(f"ix_terminology_passes_{column}"), table_name="terminology_passes")
    op.drop_table("terminology_passes")

    # Кандидатам глав в прежней схеме места нет: владельцем там может быть
    # только документ. Их решения остаются в словаре — уходит лишь вопрос.
    op.execute("DELETE FROM term_candidates WHERE chapter_id IS NOT NULL")
    op.drop_constraint(
        op.f("ck_term_candidates_term_candidate_owner"), "term_candidates", type_="check"
    )
    op.drop_constraint("term_candidate_in_chapter", "term_candidates", type_="unique")
    op.drop_index(op.f("ix_term_candidates_chapter_id"), table_name="term_candidates")
    op.drop_constraint(
        op.f("fk_term_candidates_first_block_id_blocks"), "term_candidates", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_term_candidates_chapter_id_chapters"), "term_candidates", type_="foreignkey"
    )
    op.drop_column("term_candidates", "first_block_id")
    op.drop_column("term_candidates", "chapter_id")
    op.alter_column("term_candidates", "document_id", nullable=False)

    # Оба правила проверяются одинаково — исходной формой рядом с
    # переводом, — поэтому в прежний флажок уходят оба.
    op.add_column(
        "glossary_terms",
        sa.Column("expand_on_first_use", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE glossary_terms SET expand_on_first_use = TRUE WHERE first_use_rule <> 'NONE'"
    )
    op.alter_column("glossary_terms", "expand_on_first_use", server_default=None)
    op.drop_column("glossary_terms", "first_use_rule")
    sa.Enum(name="first_use_rule").drop(op.get_bind(), checkfirst=True)
    op.drop_column("glossary_terms", "domain")
    op.drop_column("glossary_terms", "allowed_variants")

    # Значение из перечисления в Postgres не удаляется — перечисление
    # пересоздаётся без него, вместе со счётчиками версий глоссария.
    op.execute("DELETE FROM code_counters WHERE kind = 'GLOSSARY_VERSION'")
    op.execute("ALTER TYPE code_kind RENAME TO code_kind_glossary")
    op.execute(
        "CREATE TYPE code_kind AS ENUM "
        "('BOOK', 'CHAPTER', 'BLOCK', 'FIGURE', 'TABLE', 'EQUATION', 'CODE', 'ISSUE')"
    )
    op.execute(
        "ALTER TABLE code_counters ALTER COLUMN kind TYPE code_kind USING kind::text::code_kind"
    )
    op.execute("DROP TYPE code_kind_glossary")
