"""Приём документов: имя исходного файла и защита от повторной загрузки

Revision ID: 0003_document_intake
Revises: 0002_refresh_sessions
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_document_intake"
down_revision: str | None = "0002_refresh_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("original_filename", sa.String(length=255), nullable=True))
    # Частичный уникальный индекс: один и тот же файл не заводится в проекте
    # дважды. Условие обязательно — документов без контрольной суммы может
    # быть сколько угодно, и без него они конфликтовали бы между собой.
    op.create_index(
        "documents_project_content_hash",
        "documents",
        ["project_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("documents_project_content_hash", table_name="documents")
    op.drop_column("documents", "original_filename")
