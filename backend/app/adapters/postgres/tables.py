from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

# Each aggregate is one jsonb body. Only the fields a query filters on or a constraint
# guards get their own column, and the mappers fill both from the same domain object.
metadata = MetaData()

mandates = Table(
    "mandates",
    metadata,
    Column("buyer_id", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("body", JSONB, nullable=False),
    # Old versions stay, so an order can always name the rules it ran under.
    PrimaryKeyConstraint("buyer_id", "version"),
)

agent_keys = Table(
    "agent_keys",
    metadata,
    # Only the hash: a leaked table must not give an attacker a working key.
    Column("key_hash", Text, primary_key=True),
    Column("buyer_id", Text, nullable=False),
    Column("body", JSONB, nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("user_id", Text, primary_key=True),
    Column("body", JSONB, nullable=False),
)

offers = Table(
    "offers",
    metadata,
    Column("offer_id", Text, primary_key=True),
    Column("buyer_id", Text, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=False),
    Column("body", JSONB, nullable=False),
)

carts = Table(
    "carts",
    metadata,
    Column("cart_id", Text, primary_key=True),
    Column("buyer_id", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("approve_before", DateTime(timezone=True), nullable=False),
    Column("body", JSONB, nullable=False),
    # The inbox lists one buyer's carts by state.
    Index("ix_carts_buyer_id_state", "buyer_id", "state"),
)

orders = Table(
    "orders",
    metadata,
    Column("order_id", Text, primary_key=True),
    # One order per cart: checkout and approve can race on the same cart.
    Column("cart_id", Text, nullable=False, unique=True),
    Column("buyer_id", Text, nullable=False, index=True),
    # The day limit sums every order with a line on one date.
    Column("delivery_dates", ARRAY(Date), nullable=False),
    Column("body", JSONB, nullable=False),
)

audit_records = Table(
    "audit_records",
    metadata,
    # Keeps the insert order, which created_at alone cannot when two records share a time.
    Column("seq", BigInteger, Identity(), primary_key=True),
    Column("record_id", Text, nullable=False, unique=True),
    Column("cart_id", Text, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("body", JSONB, nullable=False),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("buyer_id", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("result_id", Text, nullable=False),
    PrimaryKeyConstraint("buyer_id", "key"),
)
