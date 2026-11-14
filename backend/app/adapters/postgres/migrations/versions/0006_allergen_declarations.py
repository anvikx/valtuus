"""Preserve allergen declaration types in grouped JSON.

This type change requires the new application image; an image-only rollback is unsupported.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "allergen",
        existing_type=pg.ARRAY(sa.Text()),
        type_=pg.JSONB(),
        existing_nullable=False,
        postgresql_using="jsonb_build_object('CONTAINS', allergen, 'MAY_CONTAIN', '[]'::jsonb)",
    )
    # The old array merged both types, so only a source reimport can establish certainty.
    op.execute("UPDATE products SET allergen_status = 'UNKNOWN'")


def downgrade() -> None:
    raise RuntimeError("Restore a database backup to reverse the allergen conversion")
