"""Очередь заданий на перевод и настройки уведомлений

Книга переводится часами, и держать ради этого открытой вкладку нельзя.
Человек ставит книгу в очередь и уходит; работает отдельный процесс, а по
готовности приходит уведомление — на почту или в чат.

Очередь в базе, а не в брокере: `FOR UPDATE SKIP LOCKED` даёт ровно то,
что от неё нужно, а сорвавшееся задание остаётся видимой строкой с
причиной отказа, а не исчезает в чужой системе.

Revision ID: 0009_translation_jobs
Revises: 0008_user_access
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_translation_jobs"
down_revision: str | None = "0008_user_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Значения перечисления — ИМЕНА членов заглавными: SQLAlchemy пишет в
    # базу `.name`, а не `.value`.
    op.create_table(
        "translation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state",
            sa.Enum("WAITING", "RUNNING", "DONE", "FAILED", "CANCELLED", name="job_state"),
            nullable=False,
        ),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("worker", sa.String(length=120), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("segments_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segments_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
    )

    op.create_index("ix_translation_jobs_organization_id", "translation_jobs", ["organization_id"])
    op.create_index("ix_translation_jobs_document_id", "translation_jobs", ["document_id"])
    op.create_index("translation_jobs_queue", "translation_jobs", ["state", "created_at"])

    # Одна книга — одно живое задание. Двойное нажатие иначе заводит второе,
    # которое будет упираться в занятый документ и ляжет с отказом.
    op.create_index(
        "translation_jobs_live_document",
        "translation_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING')"),
    )

    op.create_table(
        "notification_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Не «кому», а «кому ещё»: письмо и так уходит тому, кто поставил
        # книгу в очередь, — на почту его учётной записи.
        sa.Column("email_extra", sa.String(length=320), nullable=True),
        sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Ник вводит человек; номер разговора подставляет система — узнать
        # его неоткуда, пока человек не написал боту сам. Ключа бота здесь
        # нет и не будет: бот один на площадку и живёт в её настройках.
        sa.Column("telegram_username", sa.String(length=32), nullable=True),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        # Один набор настроек на пространство — ограничением базы, а не
        # уговором: два набора означали бы, что чтение и запись попадают в
        # разные строки.
        sa.UniqueConstraint("organization_id", name="notification_settings_organization"),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")

    op.drop_index("translation_jobs_live_document", table_name="translation_jobs")
    op.drop_index("translation_jobs_queue", table_name="translation_jobs")
    op.drop_index("ix_translation_jobs_document_id", table_name="translation_jobs")
    op.drop_index("ix_translation_jobs_organization_id", table_name="translation_jobs")
    op.drop_table("translation_jobs")

    sa.Enum(name="job_state").drop(op.get_bind(), checkfirst=True)
