"""Phase 3: extracted_reference structured fields + review.meta.

Revision ID: 20261003_0003
Revises: 20261003_0002
Create Date: 2026-10-03

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_0003"
down_revision: Union[str, None] = "20261003_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("extracted_references", sa.Column("publisher_guess", sa.String(length=200), nullable=True))
    op.add_column("extracted_references", sa.Column("supplement_guess", sa.String(length=120), nullable=True))
    op.add_column("extracted_references", sa.Column("date_guess", sa.String(length=32), nullable=True))
    op.add_column("extracted_references", sa.Column("section_kind", sa.String(length=64), nullable=True))
    op.add_column(
        "extracted_references", sa.Column("normalization_version", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "extracted_references",
        sa.Column("resolution_state", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "extracted_references", sa.Column("selected_match_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "extracted_references",
        sa.Column("structured", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "reviews",
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("reviews", "meta")
    for col in [
        "structured",
        "selected_match_id",
        "resolution_state",
        "normalization_version",
        "section_kind",
        "date_guess",
        "supplement_guess",
        "publisher_guess",
    ]:
        op.drop_column("extracted_references", col)
