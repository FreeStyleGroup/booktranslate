"""Учёт расхода на перевод документа

Токены, а не деньги: цены меняются, а потраченное на эту книгу —
исторический факт. Стоимость собирается на лету по прейскуранту
(app/services/pricing.py), и старый отчёт от смены тарифа не портится.

Revision ID: 0006_document_usage
Revises: 0005_term_candidates
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_document_usage"
down_revision: str | None = "0005_term_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Счётчики нарастающим итогом по всем запускам перевода документа.
COUNTERS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens")


def upgrade() -> None:
    for name in COUNTERS:
        op.add_column(
            "documents",
            sa.Column(name, sa.BigInteger(), nullable=False, server_default="0"),
        )

    op.add_column("documents", sa.Column("translated_by", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "translated_by")

    for name in reversed(COUNTERS):
        op.drop_column("documents", name)
