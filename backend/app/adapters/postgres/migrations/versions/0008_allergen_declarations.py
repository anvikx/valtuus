"""Add typed declarations and translations while keeping old-image columns writable."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null means a legacy writer: neither types nor translations can be reconstructed.
    op.add_column("products", sa.Column("allergen_declarations", pg.JSONB(), nullable=True))
    op.add_column("products", sa.Column("names", pg.JSONB(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Migrations are forward only; restore the previous application image")
