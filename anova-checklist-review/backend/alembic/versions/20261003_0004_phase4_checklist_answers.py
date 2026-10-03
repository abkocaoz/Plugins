"""Phase 4: checklist_answers AI vs human fields.

Revision ID: 20261003_0004
Revises: 20261003_0003
Create Date: 2026-10-03

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_0004"
down_revision: Union[str, None] = "20261003_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "checklist_answers",
        sa.Column("ai_proposal", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("checklist_answers", sa.Column("human_decision", sa.String(length=64), nullable=True))
    op.add_column("checklist_answers", sa.Column("chapter_text", sa.Text(), nullable=True))
    op.add_column("checklist_answers", sa.Column("comment_text", sa.Text(), nullable=True))
    op.add_column("checklist_answers", sa.Column("excel_answer_cell", sa.String(length=32), nullable=True))
    op.add_column("checklist_answers", sa.Column("excel_chapter_cell", sa.String(length=32), nullable=True))
    op.add_column("checklist_answers", sa.Column("excel_comment_cell", sa.String(length=32), nullable=True))


def downgrade() -> None:
    for col in [
        "excel_comment_cell",
        "excel_chapter_cell",
        "excel_answer_cell",
        "comment_text",
        "chapter_text",
        "human_decision",
        "ai_proposal",
    ]:
        op.drop_column("checklist_answers", col)
