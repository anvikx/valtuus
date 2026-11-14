"""Alembic entry point. The app passes its own connection; the CLI reads DATABASE_URL.

Every migration must keep the previous image working. deploy.sh rolls back the image
but not the schema, so the old code then runs on the new schema. Add tables and
columns; rename or drop only in a later deploy, after no running image reads them.
"""

import os

from alembic import context
from sqlalchemy import Connection, create_engine

from app.adapters.postgres.tables import metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_from_env() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is empty, so there is no database to migrate")

    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            _run(connection)
    finally:
        engine.dispose()


_shared = context.config.attributes.get("connection")
if _shared is None:
    _run_from_env()
else:
    _run(_shared)
