"""Главы книги с утверждаемыми границами

До перевода каждой главы утверждаются её начало, конец и заголовки.
Глава получает постоянный код (`CH03`) при утверждении, место в книге
(`ordinal`) — отдельно: место меняется при разделении и объединении,
код — никогда.

Границы — номера блоков основного источника в порядке разбора, вместе с
самим файлом и версией разбора: без них номера ничего не значат.

Revision ID: 0013_chapters
Revises: 0012_books_and_sources
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_chapters"
down_revision: str | None = "0012_books_and_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chapters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Пусто у черновика: номер кода выдаётся при утверждении.
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column("sections", postgresql.JSONB(), nullable=False),
        # Значения перечислений — ИМЕНА членов заглавными: SQLAlchemy пишет
        # в базу `.name`, а не `.value`.
        sa.Column(
            "origin",
            sa.Enum("HEADING", "PATH", "PAGE", "WHOLE", "MANUAL", name="chapter_origin"),
            nullable=False,
        ),
        sa.Column(
            "boundary_status",
            sa.Enum("DRAFT", "APPROVED", name="boundary_status"),
            nullable=False,
        ),
        sa.Column("boundary_version", sa.Integer(), nullable=False),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("source_end > source_start", name=op.f("ck_chapters_chapter_range")),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_chapters_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["book_editions.id"],
            name=op.f("fk_chapters_book_id_book_editions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_chapters_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        # Без каскада: удаление файла не должно молча уносить размеченные
        # по нему границы. Проверка отложена до фиксации: каскадные удаления
        # — отдельные внутренние запросы, и немедленная проверка срабатывает
        # в конце каждого. При удалении проекта каскад до документов доходит
        # раньше, чем до глав его книг, и без отсрочки удаление падало бы на
        # собственных главах.
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_chapters_source_document_id_documents"),
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chapters")),
        sa.UniqueConstraint("book_id", "number", name="chapter_number"),
        # Проверка в конце транзакции: при разделении нижестоящие главы
        # сдвигаются на одно место, и на середине сдвига две стоят на одном.
        sa.UniqueConstraint(
            "book_id", "ordinal", name="chapter_ordinal", deferrable=True, initially="DEFERRED"
        ),
    )
    op.create_index(op.f("ix_chapters_book_id"), "chapters", ["book_id"])
    op.create_index(op.f("ix_chapters_organization_id"), "chapters", ["organization_id"])
    op.create_index(op.f("ix_chapters_source_document_id"), "chapters", ["source_document_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chapters_source_document_id"), table_name="chapters")
    op.drop_index(op.f("ix_chapters_organization_id"), table_name="chapters")
    op.drop_index(op.f("ix_chapters_book_id"), table_name="chapters")
    op.drop_table("chapters")

    sa.Enum(name="boundary_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="chapter_origin").drop(op.get_bind(), checkfirst=True)
