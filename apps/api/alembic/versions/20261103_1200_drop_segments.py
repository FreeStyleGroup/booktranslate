"""Убрать прежний контур: сегменты, состояния файла, задания документов.

Текст книги живёт в блоках, перевод — в редакциях, расход — в прогонах. Поэтому
уходят таблица `segments`, состояние и расход у документа (документ теперь только
исходный файл), кандидаты в термины, привязанные к документу, и задания на документ.
Переводы прежнего контура не переносятся — так решено заказчиком.

🔥 Откат восстанавливает структуру, а не содержимое: удалённых сегментов, кандидатов
документов и заданий откат не вернёт. Перед применением делается резервная копия.

Revision ID: 0018_drop_segments
Revises: 0017_translation_revisions
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_drop_segments"
down_revision: str | None = "0017_translation_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

SEGMENT_STATUSES = ("NEW", "MACHINE", "MEMORY", "EDITED", "APPROVED", "FLAGGED")
SEGMENT_KINDS = ("PARAGRAPH", "HEADING", "LIST_ITEM", "TABLE_CELL", "CAPTION", "WARNING", "CODE")
DOCUMENT_STATUSES = ("UPLOADED", "PARSING", "PARSED", "TRANSLATING", "REVIEW", "DONE", "FAILED")


def upgrade() -> None:
    op.drop_table("segments")
    sa.Enum(name="segment_status").drop(op.get_bind())
    sa.Enum(name="segment_kind").drop(op.get_bind())

    # Кандидаты документов остаются без владельца: их главы нет.
    op.execute("DELETE FROM term_candidates WHERE chapter_id IS NULL")
    op.drop_constraint("term_candidate_owner", "term_candidates", type_="check")
    op.drop_constraint("term_candidate_in_document", "term_candidates", type_="unique")
    op.drop_index("ix_term_candidates_document_id", table_name="term_candidates")
    op.drop_column("term_candidates", "document_id")
    op.alter_column("term_candidates", "chapter_id", existing_type=UUID, nullable=False)

    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_column("documents", "status")
    op.drop_column("documents", "error")
    op.drop_column("documents", "input_tokens")
    op.drop_column("documents", "output_tokens")
    op.drop_column("documents", "cached_input_tokens")
    op.drop_column("documents", "cache_write_tokens")
    op.drop_column("documents", "translated_by")
    sa.Enum(name="document_status").drop(op.get_bind())

    op.execute("DELETE FROM translation_jobs WHERE chapter_id IS NULL OR run_id IS NULL")
    op.drop_index("translation_jobs_live_document", table_name="translation_jobs")
    op.drop_index("ix_translation_jobs_document_id", table_name="translation_jobs")
    op.drop_column("translation_jobs", "document_id")
    op.alter_column("translation_jobs", "chapter_id", existing_type=UUID, nullable=False)
    op.alter_column("translation_jobs", "run_id", existing_type=UUID, nullable=False)
    op.alter_column("translation_jobs", "segments_total", new_column_name="items_total")
    op.alter_column("translation_jobs", "segments_done", new_column_name="items_done")

    op.drop_index("translation_jobs_live_chapter", table_name="translation_jobs")
    op.create_index(
        "translation_jobs_live_chapter",
        "translation_jobs",
        ["chapter_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING')"),
    )

    # Значение перечисления в Postgres не удалить: тип пересоздаётся.
    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum("CHAPTER", name="job_kind").create(op.get_bind())
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")


def downgrade() -> None:
    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum("DOCUMENT", "CHAPTER", name="job_kind").create(op.get_bind())
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")

    op.drop_index("translation_jobs_live_chapter", table_name="translation_jobs")
    op.create_index(
        "translation_jobs_live_chapter",
        "translation_jobs",
        ["chapter_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING') AND chapter_id IS NOT NULL"),
    )

    op.alter_column("translation_jobs", "items_total", new_column_name="segments_total")
    op.alter_column("translation_jobs", "items_done", new_column_name="segments_done")
    op.alter_column("translation_jobs", "run_id", existing_type=UUID, nullable=True)
    op.alter_column("translation_jobs", "chapter_id", existing_type=UUID, nullable=True)
    op.add_column(
        "translation_jobs",
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE")),
    )
    op.create_index("ix_translation_jobs_document_id", "translation_jobs", ["document_id"])
    op.create_index(
        "translation_jobs_live_document",
        "translation_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING')"),
    )

    status = sa.Enum(*DOCUMENT_STATUSES, name="document_status")
    status.create(op.get_bind())
    op.add_column(
        "documents", sa.Column("status", status, nullable=False, server_default="UPLOADED")
    )
    op.alter_column("documents", "status", server_default=None)
    op.create_index("ix_documents_status", "documents", ["status"])
    op.add_column("documents", sa.Column("error", sa.Text(), nullable=True))
    for column in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"):
        op.add_column(
            "documents", sa.Column(column, sa.BigInteger(), nullable=False, server_default="0")
        )
        op.alter_column("documents", column, server_default=None)
    op.add_column("documents", sa.Column("translated_by", sa.String(length=120), nullable=True))

    op.alter_column("term_candidates", "chapter_id", existing_type=UUID, nullable=True)
    op.add_column(
        "term_candidates",
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE")),
    )
    op.create_index("ix_term_candidates_document_id", "term_candidates", ["document_id"])
    op.create_unique_constraint(
        "term_candidate_in_document", "term_candidates", ["document_id", "source_term_normalized"]
    )
    op.create_check_constraint(
        "term_candidate_owner", "term_candidates", "num_nonnulls(document_id, chapter_id) = 1"
    )

    op.create_table(
        "segments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id", UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Enum(*SEGMENT_KINDS, name="segment_kind"), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("target_text", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum(*SEGMENT_STATUSES, name="segment_status"), nullable=False),
        sa.Column("source_location", postgresql.JSONB(), nullable=True),
        sa.Column("translation_source", sa.String(length=120), nullable=True),
        sa.Column("quality", postgresql.JSONB(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("document_id", "position", name="uq_segments_document_position"),
    )
    op.create_index("ix_segments_organization_id", "segments", ["organization_id"])
    op.create_index("ix_segments_document_id", "segments", ["document_id"])
    op.create_index("ix_segments_status", "segments", ["status"])
    op.create_index("ix_segments_quality_score", "segments", ["quality_score"])
