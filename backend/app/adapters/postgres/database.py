from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine

_MIGRATIONS = Path(__file__).parent / "migrations"
# ponytail: sized for one uvicorn worker and its thread pool. Raise both, and the
# server's max_connections, if requests wait on the pool.
_POOL_SIZE = 5
_MAX_OVERFLOW = 5


@dataclass
class _OpenTransaction:
    connection: Connection
    # Set when a nested transaction() fails, so the caller cannot commit half a change.
    is_doomed: bool = False


class Database:
    """One engine, and the connection of the transaction open in this thread or task."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._open: ContextVar[_OpenTransaction | None] = ContextVar(
            "open_transaction",
            default=None,
        )

    @classmethod
    def from_url(cls, url: SecretStr) -> "Database":
        engine = create_engine(
            url.get_secret_value(),
            pool_size=_POOL_SIZE,
            max_overflow=_MAX_OVERFLOW,
            pool_pre_ping=True,
            # Bound values can hold buyer data; keep them out of error messages and logs.
            hide_parameters=True,
        )
        return cls(engine)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """A nested call joins the open transaction, so all of it commits or none of it."""
        current = self._open.get()
        if current is not None:
            yield from _join(current)
            return

        with self._engine.begin() as connection:
            opened = _OpenTransaction(connection)
            token = self._open.set(opened)
            try:
                yield
                if opened.is_doomed:
                    raise RuntimeError("a nested transaction failed, so nothing is committed")
            finally:
                self._open.reset(token)

    def writer(self) -> Connection:
        """Without this rule, a write outside transaction() would commit alone."""
        current = self._open.get()
        if current is None:
            raise RuntimeError("a write needs an open transaction")

        return current.connection

    @contextmanager
    def reader(self) -> Iterator[Connection]:
        current = self._open.get()
        if current is not None:
            yield current.connection
            return

        with self._engine.connect() as connection:
            yield connection

    def migrate(self) -> None:
        config = Config()
        config.set_main_option("script_location", str(_MIGRATIONS))
        with self._engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def close(self) -> None:
        self._engine.dispose()


def _join(current: _OpenTransaction) -> Iterator[None]:
    try:
        yield
    except Exception:
        current.is_doomed = True
        raise
