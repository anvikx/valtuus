"""Tie each session to the password it was opened with, so a new password logs out."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The old rows have no tag, so they end now. The main user logs in once more.
    op.execute("DELETE FROM sessions")
    # The default lets the previous image still log in after a rollback. An empty tag never
    # matches, so the new image refuses those sessions and the main user logs in again.
    op.add_column(
        "sessions",
        sa.Column("password_tag", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("sessions", "password_tag")
