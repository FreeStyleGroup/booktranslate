"""Неизменяемый мастер главы, блоки с постоянными кодами, части для модели

Мастер — снимок исходного текста главы, который не правится никогда:
ошибка извлечения исправляется новой версией. Версия хранит список своих
блоков и контрольную сумму по нему.

Блок — логический абзац, заголовок или пункт с кодом `CH03-B0042`. Текст
блока неизменяем: изменился текст — это новый блок, а прежний выводится
из действия. Неизменившиеся блоки сохраняют коды между версиями мастера.

Части блока — техническая нарезка для модели; их склейка — ровно текст
блока, и смена нарезки кодов блоков не трогает.

Revision ID: 0014_master_and_blocks
Revises: 0013_chapters
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_master_and_blocks"
down_revision: str | None = "0013_chapters"
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


def upgrade() -> None:
    op.create_table(
        "chapter_masters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("boundary_version", sa.Integer(), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("block_ids", postgresql.JSONB(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_chapter_masters_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_chapter_masters_chapter_id_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_chapter_masters_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_chapter_masters_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        # Отложено до фиксации — как у главы: немедленная проверка
        # споткнулась бы о каскадное удаление проекта.
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_chapter_masters_source_document_id_documents"),
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["chapter_masters.id"],
            name=op.f("fk_chapter_masters_supersedes_id_chapter_masters"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chapter_masters")),
        sa.UniqueConstraint("chapter_id", "version", name="chapter_master_version"),
    )
    op.create_index(op.f("ix_chapter_masters_chapter_id"), "chapter_masters", ["chapter_id"])
    op.create_index(
        op.f("ix_chapter_masters_organization_id"), "chapter_masters", ["organization_id"]
    )
    op.create_index(
        op.f("ix_chapter_masters_source_document_id"), "chapter_masters", ["source_document_id"]
    )

    op.create_table(
        "blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("master_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_block_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        # Значения перечисления — ИМЕНА членов заглавными: SQLAlchemy пишет
        # в базу `.name`, а не `.value`. Тип свой, а не `segment_kind`: тот
        # уйдёт вместе с прежним контуром.
        sa.Column(
            "kind",
            sa.Enum(
                "PARAGRAPH",
                "HEADING",
                "LIST_ITEM",
                "TABLE_CELL",
                "CAPTION",
                "WARNING",
                "CODE",
                name="block_kind",
            ),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_location", postgresql.JSONB(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_blocks_chapter_id_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["chapter_masters.id"],
            name=op.f("fk_blocks_master_id_chapter_masters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_blocks_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_block_id"],
            ["blocks.id"],
            name=op.f("fk_blocks_parent_block_id_blocks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blocks")),
        sa.UniqueConstraint("chapter_id", "number", name="block_number"),
    )
    op.create_index(op.f("ix_blocks_chapter_id"), "blocks", ["chapter_id"])
    op.create_index(op.f("ix_blocks_master_id"), "blocks", ["master_id"])
    op.create_index(op.f("ix_blocks_organization_id"), "blocks", ["organization_id"])
    op.create_index("blocks_current", "blocks", ["chapter_id", "active", "ordinal"])

    op.create_table(
        "segment_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name=op.f("fk_segment_chunks_block_id_blocks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_segment_chunks_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_segment_chunks")),
        sa.UniqueConstraint("block_id", "chunk_index", name="segment_chunk_index"),
    )
    op.create_index(op.f("ix_segment_chunks_block_id"), "segment_chunks", ["block_id"])
    op.create_index(
        op.f("ix_segment_chunks_organization_id"), "segment_chunks", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_segment_chunks_organization_id"), table_name="segment_chunks")
    op.drop_index(op.f("ix_segment_chunks_block_id"), table_name="segment_chunks")
    op.drop_table("segment_chunks")

    op.drop_index("blocks_current", table_name="blocks")
    op.drop_index(op.f("ix_blocks_organization_id"), table_name="blocks")
    op.drop_index(op.f("ix_blocks_master_id"), table_name="blocks")
    op.drop_index(op.f("ix_blocks_chapter_id"), table_name="blocks")
    op.drop_table("blocks")

    op.drop_index(op.f("ix_chapter_masters_source_document_id"), table_name="chapter_masters")
    op.drop_index(op.f("ix_chapter_masters_organization_id"), table_name="chapter_masters")
    op.drop_index(op.f("ix_chapter_masters_chapter_id"), table_name="chapter_masters")
    op.drop_table("chapter_masters")

    sa.Enum(name="block_kind").drop(op.get_bind(), checkfirst=True)
