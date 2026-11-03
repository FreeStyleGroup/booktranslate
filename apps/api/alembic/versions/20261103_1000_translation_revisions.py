"""Прогоны перевода и неизменяемые редакции блоков.

Перевод перестаёт быть полем строки и становится цепочкой редакций: каждая
запись неизменяема, текущую указывает блок. Неизменяемость держит сама база:
триггер отвергает обновление содержимого редакции, откуда бы оно ни пришло.
Обновлять разрешено только ссылки на то, что может исчезнуть (запись памяти,
автор), — иначе удаление такой записи падало бы на обнулении ссылки.

У задания появляются вид, глава и прогон: очередь обобщается, и дальше в неё
встанут проверки, регрессия и сборка. `document_id` становится необязательным
— задание главы к файлу не привязано.

Revision ID: 0017_translation_revisions
Revises: 0016_glossary_versions
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_translation_revisions"
down_revision: str | None = "0016_glossary_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "translation_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "book_id", UUID, sa.ForeignKey("book_editions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "chapter_id", UUID, sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "master_id",
            UUID,
            sa.ForeignKey("chapter_masters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("DRAFT", "RETRANSLATE", name="translation_run_kind"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column(
            "glossary_version_id",
            UUID,
            sa.ForeignKey("glossary_versions.id", deferrable=True, initially="DEFERRED"),
            nullable=True,
        ),
        sa.Column("ignore_terminology", sa.Boolean(), nullable=False),
        sa.Column("bypass_reason", sa.Text(), nullable=True),
        sa.Column("selection", postgresql.JSONB(), nullable=False),
        sa.Column(
            "requested_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("blocks_total", sa.Integer(), nullable=False),
        sa.Column("from_model", sa.Integer(), nullable=False),
        sa.Column("from_memory", sa.Integer(), nullable=False),
        sa.Column("copied", sa.Integer(), nullable=False),
        sa.Column("rejections", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "NOT ignore_terminology OR bypass_reason IS NOT NULL",
            name="translation_run_bypass_reason",
        ),
    )
    op.create_index("ix_translation_runs_organization_id", "translation_runs", ["organization_id"])
    op.create_index("ix_translation_runs_book_id", "translation_runs", ["book_id"])
    op.create_index("translation_runs_chapter", "translation_runs", ["chapter_id", "created_at"])

    op.create_table(
        "translation_revisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("block_id", UUID, sa.ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum("DRAFT", "WORKING", "FINAL_CANDIDATE", name="revision_stage"),
            nullable=False,
        ),
        sa.Column(
            "origin",
            sa.Enum("MODEL", "MEMORY", "HUMAN", "COPY", name="revision_origin"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("translation_runs.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "supersedes_id",
            UUID,
            sa.ForeignKey("translation_revisions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "memory_unit_id",
            UUID,
            sa.ForeignKey("translation_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "copied_from_id",
            UUID,
            sa.ForeignKey("translation_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("block_id", "revision_no", name="translation_revision_no"),
    )
    op.create_index(
        "ix_translation_revisions_organization_id", "translation_revisions", ["organization_id"]
    )
    op.create_index("ix_translation_revisions_block_id", "translation_revisions", ["block_id"])
    op.create_index(
        "translation_revision_run_block",
        "translation_revisions",
        ["run_id", "block_id"],
        unique=True,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )

    # Список столбцов перечислен: обнуление `memory_unit_id`, `copied_from_id`
    # и `created_by_id` при удалении записи памяти, соседней редакции или
    # пользователя — законное обновление служебной ссылки, а не правка текста.
    op.execute(
        """
        CREATE FUNCTION translation_revision_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Редакция перевода % неизменяема', OLD.id
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER translation_revisions_immutable
        BEFORE UPDATE OF block_id, revision_no, stage, origin, text, run_id, supersedes_id
        ON translation_revisions
        FOR EACH ROW EXECUTE FUNCTION translation_revision_immutable()
        """
    )

    op.add_column("blocks", sa.Column("current_revision_id", UUID, nullable=True))
    op.create_foreign_key(
        "blocks_current_revision_id_fkey",
        "blocks",
        "translation_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "object_verifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "object_id", UUID, sa.ForeignKey("book_objects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "verified_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index(
        "ix_object_verifications_organization_id", "object_verifications", ["organization_id"]
    )
    op.create_index(
        "object_verifications_latest", "object_verifications", ["object_id", "created_at"]
    )

    job_kind = sa.Enum("DOCUMENT", "CHAPTER", name="job_kind")
    job_kind.create(op.get_bind())
    op.add_column(
        "translation_jobs", sa.Column("kind", job_kind, nullable=False, server_default="DOCUMENT")
    )
    op.alter_column("translation_jobs", "kind", server_default=None)
    op.alter_column("translation_jobs", "document_id", existing_type=UUID, nullable=True)
    op.add_column(
        "translation_jobs",
        sa.Column("chapter_id", UUID, sa.ForeignKey("chapters.id", ondelete="CASCADE")),
    )
    op.add_column(
        "translation_jobs",
        sa.Column("run_id", UUID, sa.ForeignKey("translation_runs.id", ondelete="CASCADE")),
    )
    op.create_index("ix_translation_jobs_chapter_id", "translation_jobs", ["chapter_id"])
    op.create_index("ix_translation_jobs_run_id", "translation_jobs", ["run_id"], unique=True)
    op.create_index(
        "translation_jobs_live_chapter",
        "translation_jobs",
        ["chapter_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING') AND chapter_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("translation_jobs_live_chapter", table_name="translation_jobs")
    op.drop_index("ix_translation_jobs_run_id", table_name="translation_jobs")
    op.drop_index("ix_translation_jobs_chapter_id", table_name="translation_jobs")
    # Задание главы к файлу не привязано и без своей главы теряет смысл.
    op.execute("DELETE FROM translation_jobs WHERE document_id IS NULL")
    op.drop_column("translation_jobs", "run_id")
    op.drop_column("translation_jobs", "chapter_id")
    op.alter_column("translation_jobs", "document_id", existing_type=UUID, nullable=False)
    op.drop_column("translation_jobs", "kind")
    sa.Enum(name="job_kind").drop(op.get_bind())

    op.drop_table("object_verifications")

    op.drop_constraint("blocks_current_revision_id_fkey", "blocks", type_="foreignkey")
    op.drop_column("blocks", "current_revision_id")

    op.execute("DROP TRIGGER translation_revisions_immutable ON translation_revisions")
    op.execute("DROP FUNCTION translation_revision_immutable()")
    op.drop_table("translation_revisions")
    sa.Enum(name="revision_origin").drop(op.get_bind())
    sa.Enum(name="revision_stage").drop(op.get_bind())

    op.drop_table("translation_runs")
    sa.Enum(name="translation_run_kind").drop(op.get_bind())
