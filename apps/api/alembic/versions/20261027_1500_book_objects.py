"""Специальные объекты главы: рисунки, таблицы, формулы, листинги

Объект — постоянный код (`CH03-FIG001`) и контрольная сумма содержимого;
текст, который в нём переводится, живёт в обычных блоках. Объект
неизменяем: изменилось содержимое — это новый объект с родством.

Упоминания объектов в тексте блоков — производные, пересчитываются при
каждом извлечении мастера.

Версия мастера получает список своих объектов, а её сумма — объекты
вместе с блоками. Сумма уже извлечённых версий пересчитывается: объектов у
них нет, содержимое прежнее, сменилась только каноническая запись.

Нумерация объектов — у каждого вида своя, поэтому общий вид счётчика
`OBJECT` становится четырьмя. Счётчиков этого вида нет: объекты до этой
миграции не выдавались.

Revision ID: 0015_book_objects
Revises: 0014_master_and_blocks
Create Date: 2026-10-27
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_book_objects"
down_revision: str | None = "0014_master_and_blocks"
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
    # Значение не используется в этой же транзакции — так Postgres 12+
    # разрешает пополнять перечисление внутри неё.
    op.execute("ALTER TYPE code_kind RENAME VALUE 'OBJECT' TO 'FIGURE'")
    op.execute("ALTER TYPE code_kind ADD VALUE 'TABLE' AFTER 'FIGURE'")
    op.execute("ALTER TYPE code_kind ADD VALUE 'EQUATION' AFTER 'TABLE'")
    op.execute("ALTER TYPE code_kind ADD VALUE 'CODE' AFTER 'EQUATION'")

    op.create_table(
        "book_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("master_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_object_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "type",
            sa.Enum("FIGURE", "TABLE", "EQUATION", "CODE", name="object_type"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("source_location", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("caption_block_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=40), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["caption_block_id"],
            ["blocks.id"],
            name=op.f("fk_book_objects_caption_block_id_blocks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            name=op.f("fk_book_objects_chapter_id_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["master_id"],
            ["chapter_masters.id"],
            name=op.f("fk_book_objects_master_id_chapter_masters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_book_objects_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_object_id"],
            ["book_objects.id"],
            name=op.f("fk_book_objects_parent_object_id_book_objects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_objects")),
        sa.UniqueConstraint("chapter_id", "type", "number", name="book_object_number"),
    )
    op.create_index(op.f("ix_book_objects_chapter_id"), "book_objects", ["chapter_id"])
    op.create_index(op.f("ix_book_objects_master_id"), "book_objects", ["master_id"])
    op.create_index(op.f("ix_book_objects_organization_id"), "book_objects", ["organization_id"])
    op.create_index("book_objects_current", "book_objects", ["chapter_id", "active", "type"])

    op.create_table(
        "object_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("LINK", "LABEL", name="object_reference_kind"),
            nullable=False,
        ),
        sa.Column("phrase", sa.String(length=200), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name=op.f("fk_object_references_block_id_blocks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["book_objects.id"],
            name=op.f("fk_object_references_object_id_book_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_object_references_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_object_references")),
        sa.UniqueConstraint("block_id", "object_id", name="object_reference_pair"),
    )
    op.create_index(op.f("ix_object_references_block_id"), "object_references", ["block_id"])
    op.create_index(op.f("ix_object_references_object_id"), "object_references", ["object_id"])
    op.create_index(
        op.f("ix_object_references_organization_id"), "object_references", ["organization_id"]
    )

    # Пустой список у уже извлечённых версий — правда: объектов у них нет.
    # Значение по умолчанию нужно только на время добавления колонки.
    op.add_column(
        "chapter_masters",
        sa.Column(
            "objects", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )
    op.alter_column("chapter_masters", "objects", server_default=None)

    _rewrite_checksums(_with_objects)


def downgrade() -> None:
    _rewrite_checksums(_blocks_only)
    op.drop_column("chapter_masters", "objects")

    op.drop_index(op.f("ix_object_references_organization_id"), table_name="object_references")
    op.drop_index(op.f("ix_object_references_object_id"), table_name="object_references")
    op.drop_index(op.f("ix_object_references_block_id"), table_name="object_references")
    op.drop_table("object_references")
    sa.Enum(name="object_reference_kind").drop(op.get_bind(), checkfirst=True)

    op.drop_index("book_objects_current", table_name="book_objects")
    op.drop_index(op.f("ix_book_objects_organization_id"), table_name="book_objects")
    op.drop_index(op.f("ix_book_objects_master_id"), table_name="book_objects")
    op.drop_index(op.f("ix_book_objects_chapter_id"), table_name="book_objects")
    op.drop_table("book_objects")
    sa.Enum(name="object_type").drop(op.get_bind(), checkfirst=True)

    # Значение из перечисления в Postgres не удаляется — перечисление
    # пересоздаётся. Счётчики таблиц, формул и листингов уходят вместе с
    # объектами, которые они нумеровали; счётчик рисунков снова общий.
    op.execute("DELETE FROM code_counters WHERE kind IN ('TABLE', 'EQUATION', 'CODE')")
    op.execute("ALTER TYPE code_kind RENAME TO code_kind_objects")
    op.execute("CREATE TYPE code_kind AS ENUM ('BOOK', 'CHAPTER', 'BLOCK', 'OBJECT', 'ISSUE')")
    op.execute(
        "ALTER TABLE code_counters ALTER COLUMN kind TYPE code_kind USING "
        "(CASE kind::text WHEN 'FIGURE' THEN 'OBJECT' ELSE kind::text END)::code_kind"
    )
    op.execute("DROP TYPE code_kind_objects")


# Каноническая запись суммы версии — копия той, что в приложении на момент
# миграции, а не вызов приложения: миграция обязана давать тот же
# результат и тогда, когда код приложения уйдёт дальше.
def _with_objects(blocks: list[list[str]]) -> str:
    return _sha256({"blocks": blocks, "objects": []})


def _blocks_only(blocks: list[list[str]]) -> str:
    return _sha256(blocks)


def _sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _rewrite_checksums(canonical: Any) -> None:
    connection = op.get_bind()
    masters = connection.execute(sa.text("SELECT id, block_ids FROM chapter_masters")).all()

    for master_id, block_ids in masters:
        rows = connection.execute(
            sa.text(
                "SELECT id::text, kind::text, source_text FROM blocks WHERE id::text = ANY(:ids)"
            ),
            {"ids": block_ids},
        ).all()
        # Вид хранится именем члена перечисления, а в сумму входит его
        # значение — то же имя строчными.
        found = {row[0]: [row[1].lower(), row[2]] for row in rows}

        connection.execute(
            sa.text("UPDATE chapter_masters SET checksum = :checksum WHERE id = :id"),
            {"checksum": canonical([found[item] for item in block_ids]), "id": master_id},
        )
