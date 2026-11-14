"""Keep the content unit and its source, so search can tell L, KG and pieces apart."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: a rollback image still inserts rows without the columns, and the next
    # catalog load fills them.
    op.add_column("products", sa.Column("content_unit", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("content_source", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Migrations are forward only; restore the previous application image")
