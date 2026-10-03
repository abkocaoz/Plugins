"""Phase 2: jobs.idempotency_key for extract/index stages.

Revision ID: 20261003_0002
Revises: 20261003_0001
Create Date: 2026-10-03

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0002"
down_revision: Union[str, None] = "20261003_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(length=300), nullable=True))
    op.create_unique_constraint("uq_jobs_idempotency_key", "jobs", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    op.drop_column("jobs", "idempotency_key")
