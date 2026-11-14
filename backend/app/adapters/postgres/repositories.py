from collections.abc import Sequence
from datetime import date, datetime

from pydantic import TypeAdapter
from sqlalchemy import (
    Connection,
    Insert,
    Select,
    Table,
    Update,
    delete,
    func,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from app.adapters.postgres.database import Database
from app.adapters.postgres.tables import (
    agent_keys,
    audit_records,
    carts,
    idempotency_keys,
    mandates,
    offers,
    orders,
    sessions,
    users,
)
from app.domain.agent_key import AgentKey, User
from app.domain.audit import AuditRecord
from app.domain.cart import Cart
from app.domain.idempotency import IdempotencyRecord
from app.domain.mandate import Mandate
from app.domain.offer import Offer
from app.domain.order import Order
from app.domain.session import Session

# mode="json" writes Decimal as a string and datetime as ISO 8601 with its offset, so a
# body never holds a float for money. Loading runs the dataclass again, with its checks.
_MANDATE = TypeAdapter(Mandate)
_AGENT_KEY = TypeAdapter(AgentKey)
_USER = TypeAdapter(User)
_OFFER = TypeAdapter(Offer)
_CART = TypeAdapter(Cart)
_ORDER = TypeAdapter(Order)
_AUDIT = TypeAdapter(AuditRecord)


def _one[T](database: Database, adapter: TypeAdapter[T], query: Select) -> T | None:
    with database.reader() as connection:
        body = connection.execute(query).scalar_one_or_none()

    return None if body is None else adapter.validate_python(body)


def _all[T](database: Database, adapter: TypeAdapter[T], query: Select) -> list[T]:
    with database.reader() as connection:
        bodies = connection.execute(query).scalars().all()

    return [adapter.validate_python(body) for body in bodies]


def _changed(connection: Connection, statement: Insert | Update) -> bool:
    """False when ON CONFLICT DO NOTHING skipped the row, or an UPDATE matched none.

    RETURNING, not rowcount: the psycopg dialect reports rowcount -1 for these.
    """
    return connection.execute(statement.returning(true())).first() is not None


def _upsert(connection: Connection, table: Table, row: dict[str, object]) -> None:
    keys = [column.name for column in table.primary_key.columns]
    statement = insert(table).values(row)
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=keys,
            set_={name: statement.excluded[name] for name in row if name not in keys},
        ),
    )


def _version_error(expected: int, got: int) -> str:
    return f"mandate version must be {expected}, got {got}"


class PostgresMandateRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def latest(self, buyer_id: str) -> Mandate | None:
        query = (
            select(mandates.c.body)
            .where(mandates.c.buyer_id == buyer_id)
            .order_by(mandates.c.version.desc())
            .limit(1)
        )
        return _one(self._database, _MANDATE, query)

    def add(self, mandate: Mandate) -> None:
        connection = self._database.writer()
        current = connection.execute(
            select(func.max(mandates.c.version)).where(mandates.c.buyer_id == mandate.buyer_id),
        ).scalar_one()
        expected = (current or 0) + 1
        if mandate.version != expected:
            raise ValueError(_version_error(expected, mandate.version))

        statement = (
            insert(mandates)
            .values(
                buyer_id=mandate.buyer_id,
                version=mandate.version,
                body=_MANDATE.dump_python(mandate, mode="json"),
            )
            .on_conflict_do_nothing(index_elements=["buyer_id", "version"])
        )
        # Two edits read the same max; the primary key lets only one become this version.
        if not _changed(connection, statement):
            raise ValueError(_version_error(mandate.version + 1, mandate.version))


class PostgresAgentKeyRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def by_hash(self, key_hash: str) -> AgentKey | None:
        query = select(agent_keys.c.body).where(agent_keys.c.key_hash == key_hash)
        return _one(self._database, _AGENT_KEY, query)

    def for_buyer(self, buyer_id: str) -> Sequence[AgentKey]:
        query = (
            select(agent_keys.c.body)
            .where(agent_keys.c.buyer_id == buyer_id)
            .order_by(agent_keys.c.key_hash)
        )
        return _all(self._database, _AGENT_KEY, query)

    def add(self, agent_key: AgentKey) -> None:
        row = {
            "key_hash": agent_key.key_hash,
            "buyer_id": agent_key.buyer_id,
            "body": _AGENT_KEY.dump_python(agent_key, mode="json"),
        }
        _upsert(self._database.writer(), agent_keys, row)


class PostgresUserRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, user_id: str) -> User | None:
        return _one(self._database, _USER, select(users.c.body).where(users.c.user_id == user_id))

    def add(self, user: User) -> None:
        row = {
            "user_id": user.user_id,
            "body": _USER.dump_python(user, mode="json"),
        }
        _upsert(self._database.writer(), users, row)


class PostgresSessionRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, token_hash: str) -> Session | None:
        query = select(sessions).where(sessions.c.token_hash == token_hash)
        with self._database.reader() as connection:
            row = connection.execute(query).mappings().one_or_none()

        return None if row is None else Session(**row)

    def add(self, session: Session) -> None:
        row = {
            "token_hash": session.token_hash,
            "user_id": session.user_id,
            "expires_at": session.expires_at,
            "password_tag": session.password_tag,
        }
        self._database.writer().execute(insert(sessions).values(row))

    def remove(self, token_hash: str) -> None:
        self._database.writer().execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    def remove_expired(self, now: datetime) -> None:
        self._database.writer().execute(delete(sessions).where(sessions.c.expires_at <= now))


class PostgresOfferRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, offer_id: str) -> Offer | None:
        return _one(
            self._database, _OFFER, select(offers.c.body).where(offers.c.offer_id == offer_id)
        )

    def add(self, offer: Offer) -> None:
        row = {
            "offer_id": offer.offer_id,
            "buyer_id": offer.buyer_id,
            "issued_at": offer.issued_at,
            "valid_until": offer.valid_until,
            "body": _OFFER.dump_python(offer, mode="json"),
        }
        _upsert(self._database.writer(), offers, row)


def _cart_row(cart: Cart) -> dict[str, object]:
    """One mapper for add and save, so the key columns always match the body."""
    return {
        "cart_id": cart.cart_id,
        "buyer_id": cart.buyer_id,
        "state": cart.state.value,
        "approve_before": cart.approve_before,
        "body": _CART.dump_python(cart, mode="json"),
    }


class PostgresCartRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, cart_id: str) -> Cart | None:
        return _one(self._database, _CART, select(carts.c.body).where(carts.c.cart_id == cart_id))

    def for_buyer(self, buyer_id: str) -> Sequence[Cart]:
        query = (
            select(carts.c.body)
            .where(carts.c.buyer_id == buyer_id)
            .order_by(carts.c.approve_before, carts.c.cart_id)
        )
        return _all(self._database, _CART, query)

    def add(self, cart: Cart) -> None:
        statement = (
            insert(carts).values(_cart_row(cart)).on_conflict_do_nothing(index_elements=["cart_id"])
        )
        if not _changed(self._database.writer(), statement):
            raise ValueError(f"cart {cart.cart_id} exists")

    def save(self, cart: Cart) -> None:
        statement = update(carts).where(carts.c.cart_id == cart.cart_id).values(_cart_row(cart))
        if not _changed(self._database.writer(), statement):
            raise ValueError(f"cart {cart.cart_id} is unknown")


class PostgresOrderRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, order_id: str) -> Order | None:
        query = select(orders.c.body).where(orders.c.order_id == order_id)
        return _one(self._database, _ORDER, query)

    def by_cart(self, cart_id: str) -> Order | None:
        query = select(orders.c.body).where(orders.c.cart_id == cart_id)
        return _one(self._database, _ORDER, query)

    def for_day(self, buyer_id: str, delivery_date: date) -> Sequence[Order]:
        query = (
            select(orders.c.body)
            .where(
                orders.c.buyer_id == buyer_id,
                orders.c.delivery_dates.contains([delivery_date]),
            )
            .order_by(orders.c.order_id)
        )
        return _all(self._database, _ORDER, query)

    def add(self, order: Order) -> None:
        row = {
            "order_id": order.order_id,
            "cart_id": order.cart_id,
            "buyer_id": order.buyer_id,
            "delivery_dates": sorted({line.delivery_date for line in order.lines}),
            "body": _ORDER.dump_python(order, mode="json"),
        }
        statement = insert(orders).values(row).on_conflict_do_nothing(index_elements=["cart_id"])
        if not _changed(self._database.writer(), statement):
            raise ValueError(f"cart {order.cart_id} has an order")


class PostgresAuditRepository:
    """Append only. A trigger in the schema also refuses UPDATE and DELETE."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def append(self, record: AuditRecord) -> None:
        row = {
            "record_id": record.record_id,
            "cart_id": record.cart_id,
            "created_at": record.created_at,
            "body": _AUDIT.dump_python(record, mode="json"),
        }
        self._database.writer().execute(insert(audit_records).values(row))

    def for_cart(self, cart_id: str) -> Sequence[AuditRecord]:
        query = (
            select(audit_records.c.body)
            .where(audit_records.c.cart_id == cart_id)
            .order_by(audit_records.c.seq)
        )
        return _all(self._database, _AUDIT, query)


class PostgresIdempotencyRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, buyer_id: str, key: str) -> IdempotencyRecord | None:
        query = select(idempotency_keys).where(
            idempotency_keys.c.buyer_id == buyer_id,
            idempotency_keys.c.key == key,
        )
        with self._database.reader() as connection:
            row = connection.execute(query).one_or_none()

        if row is None:
            return None

        return IdempotencyRecord(
            buyer_id=row.buyer_id,
            key=row.key,
            request_hash=row.request_hash,
            result_id=row.result_id,
        )

    def add(self, record: IdempotencyRecord) -> None:
        row = {
            "buyer_id": record.buyer_id,
            "key": record.key,
            "request_hash": record.request_hash,
            "result_id": record.result_id,
        }
        statement = (
            insert(idempotency_keys)
            .values(row)
            .on_conflict_do_nothing(index_elements=["buyer_id", "key"])
        )
        if not _changed(self._database.writer(), statement):
            raise ValueError(f"idempotency key {record.key} is used")
