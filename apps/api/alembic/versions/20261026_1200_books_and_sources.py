"""Издание книги, комплект исходников с ролями, журнал решений

Книга перестаёт быть одним файлом: появляется издание, в комплект
которого входит несколько документов, и у каждого — роль. Текст берётся
только из основного источника, и он у издания один — это гарантирует
частичный уникальный индекс, а не договорённость.

Рядом — результат проверки файла (читается ли формат, есть ли текстовый
слой, сколько страниц) и журнал решений: процесс перевода построен на
утверждениях, и каждое должно оставлять след с автором и временем.

Revision ID: 0012_books_and_sources
Revises: 0011_shared_glossary
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_books_and_sources"
down_revision: str | None = "0011_shared_glossary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "book_editions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("author", sa.String(length=300), nullable=True),
        sa.Column("edition_label", sa.String(length=200), nullable=True),
        sa.Column("source_language", sa.String(length=10), nullable=False),
        sa.Column("target_language", sa.String(length=10), nullable=False),
        # Значения перечисления — ИМЕНА членов заглавными: SQLAlchemy пишет
        # в базу `.name`, а не `.value`.
        sa.Column(
            "status",
            sa.Enum("DRAFT", "IN_PROGRESS", "RELEASED", name="book_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        # Код входит в номера замечаний и потому не меняется; уникален у
        # организации, а не глобально — BK01 вправе быть у каждого.
        sa.UniqueConstraint("organization_id", "code", name="book_edition_code"),
    )
    op.create_index("ix_book_editions_organization_id", "book_editions", ["organization_id"])
    op.create_index("ix_book_editions_project_id", "book_editions", ["project_id"])
    op.create_index("ix_book_editions_status", "book_editions", ["status"])

    op.create_table(
        "source_validation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("format_ok", sa.Boolean(), nullable=False),
        sa.Column("has_text_layer", sa.Boolean(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("meta_title", sa.String(length=500), nullable=True),
        sa.Column("meta_author", sa.String(length=300), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        # Файл неизменяем: повторная загрузка заводит новый документ.
        # Значит и результат проверки у документа один.
        sa.UniqueConstraint("document_id", name="source_validation_document"),
    )
    op.create_index(
        "ix_source_validation_results_organization_id",
        "source_validation_results",
        ["organization_id"],
    )
    op.create_index(
        "ix_source_validation_results_document_id", "source_validation_results", ["document_id"]
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Пусто — решение принял сервис: автоматический режим проходит те
        # же гейты и обязан оставлять такой же след.
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        # Внешнего ключа на предмет решения нет намеренно: событие обязано
        # пережить удаление объекта, иначе исчезает то, ради чего журнал
        # заводили.
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index("ix_audit_events_kind", "audit_events", ["kind"])
    op.create_index(
        "audit_events_organization_time", "audit_events", ["organization_id", "created_at"]
    )
    op.create_index("audit_events_subject", "audit_events", ["subject_type", "subject_id"])

    op.create_table(
        "code_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("BOOK", "CHAPTER", "BLOCK", "OBJECT", "ISSUE", name="code_kind"),
            nullable=False,
        ),
        # Внешнего ключа на владельца нумерации нет намеренно: владельцы
        # разных видов лежат в разных таблицах, а счётчик обязан пережить
        # удаление владельца — иначе заново созданная глава начала бы
        # нумерацию сначала и выдала уже использованные номера.
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("kind", "owner_id", name="code_counter_scope"),
    )
    op.create_index("ix_code_counters_organization_id", "code_counters", ["organization_id"])

    # Тип создаётся отдельной командой: CREATE TYPE выполняется сам только
    # при create_table, а при добавлении колонки его не будет.
    source_role = sa.Enum(
        "PRIMARY_TEXT",
        "VISUAL_REFERENCE",
        "AUXILIARY",
        "CODE_SOURCE",
        name="document_source_role",
    )
    source_role.create(op.get_bind(), checkfirst=True)

    op.add_column("documents", sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "source_role",
            postgresql.ENUM(
                "PRIMARY_TEXT",
                "VISUAL_REFERENCE",
                "AUXILIARY",
                "CODE_SOURCE",
                name="document_source_role",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "documents_book_id_fkey",
        "documents",
        "book_editions",
        ["book_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_documents_book_id", "documents", ["book_id"])
    # Основной источник текста у издания один. Проверка перед вставкой
    # отсеивает повтор в обычном случае, но две одновременные загрузки
    # пройдут её обе — гарантию даёт только ограничение в базе.
    op.create_index(
        "documents_book_primary_text",
        "documents",
        ["book_id"],
        unique=True,
        postgresql_where=sa.text("source_role = 'PRIMARY_TEXT' AND book_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("documents_book_primary_text", table_name="documents")
    op.drop_index("ix_documents_book_id", table_name="documents")
    op.drop_constraint("documents_book_id_fkey", "documents", type_="foreignkey")
    op.drop_column("documents", "source_role")
    op.drop_column("documents", "book_id")

    op.drop_index("ix_code_counters_organization_id", table_name="code_counters")
    op.drop_table("code_counters")

    op.drop_index("audit_events_subject", table_name="audit_events")
    op.drop_index("audit_events_organization_time", table_name="audit_events")
    op.drop_index("ix_audit_events_kind", table_name="audit_events")
    op.drop_index("ix_audit_events_organization_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(
        "ix_source_validation_results_document_id", table_name="source_validation_results"
    )
    op.drop_index(
        "ix_source_validation_results_organization_id", table_name="source_validation_results"
    )
    op.drop_table("source_validation_results")

    op.drop_index("ix_book_editions_status", table_name="book_editions")
    op.drop_index("ix_book_editions_project_id", table_name="book_editions")
    op.drop_index("ix_book_editions_organization_id", table_name="book_editions")
    op.drop_table("book_editions")

    # Перечисления Postgres живут отдельно от таблиц и после drop_table
    # остаются в базе: повторный upgrade упал бы на «type already exists».
    sa.Enum(name="code_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="document_source_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="book_status").drop(op.get_bind(), checkfirst=True)
