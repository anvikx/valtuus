"""Rules only the Postgres store has: real transactions, the audit trigger, row locks."""

import dataclasses
import importlib.util
import threading
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.adapters.postgres.database import Database
from app.adapters.postgres.repositories import (
    PostgresAuditRepository,
    PostgresCartRepository,
    PostgresCartRevisionRepository,
    PostgresMandateRepository,
    PostgresOrderRepository,
)
from app.adapters.postgres.tables import (
    audit_records,
    cart_revisions,
    carts,
    mandates,
    metadata,
    orders,
)
from app.domain.cart import CartRevision
from app.domain.enums import RevisionAuthor
from tests.adapters import samples

_RACERS = 2
_MIGRATIONS = Path(__file__).parents[2] / "app/adapters/postgres/migrations/versions"


def _migration(name: str) -> ModuleType:
    """The versions folder is no package, so a migration loads from its file."""
    spec = importlib.util.spec_from_file_location(name, _MIGRATIONS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _race(work: Callable[[int], None]) -> list[BaseException | None]:
    """Starts every racer at the same barrier, so they really compete. No sleep."""
    barrier = threading.Barrier(_RACERS)
    outcomes: list[BaseException | None] = [None] * _RACERS

    def run(index: int) -> None:
        barrier.wait()
        # Kept, not raised: a thread cannot fail the test, so the test checks each outcome.
        try:
            work(index)
        except Exception as error:
            outcomes[index] = error

    threads = [threading.Thread(target=run, args=(index,)) for index in range(_RACERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    return outcomes


def _floats(value: object) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [found for item in value.values() for found in _floats(item)]
    if isinstance(value, list):
        return [found for item in value for found in _floats(item)]

    return []


def test_write_outside_a_transaction_is_refused(database: Database) -> None:
    """Otherwise a service that forgets transaction() commits a change without its audit."""
    mandates = PostgresMandateRepository(database)

    with pytest.raises(RuntimeError, match="open transaction"):
        mandates.add(samples.mandate())

    assert mandates.latest(samples.BUYER_ID) is None


def test_failure_rolls_back_every_write(database: Database) -> None:
    """A state change and its audit record are stored together or not at all."""
    mandates = PostgresMandateRepository(database)
    audit = PostgresAuditRepository(database)

    with pytest.raises(LookupError), database.transaction():
        mandates.add(samples.mandate())
        audit.append(samples.audit_record("a_1"))
        raise LookupError

    assert mandates.latest(samples.BUYER_ID) is None
    assert audit.for_cart("c_1") == []


def test_caught_inner_failure_still_rolls_back(database: Database) -> None:
    """A caller that swallows a nested failure must not commit the half it already wrote."""
    mandates = PostgresMandateRepository(database)

    with pytest.raises(RuntimeError, match="nested transaction failed"), database.transaction():
        mandates.add(samples.mandate())
        with pytest.raises(LookupError), database.transaction():
            raise LookupError

    assert mandates.latest(samples.BUYER_ID) is None


def test_audit_log_refuses_update_and_delete(database: Database) -> None:
    """The database, not only the repository, keeps the log append only."""
    with database.transaction():
        PostgresAuditRepository(database).append(samples.audit_record("a_1"))

    for statement in (update(audit_records).values(cart_id="x"), delete(audit_records)):
        with pytest.raises(DBAPIError, match="append only"), database.transaction():
            database.writer().execute(statement)

    assert len(PostgresAuditRepository(database).for_cart("c_1")) == 1


def test_cart_revisions_refuse_update_and_delete(database: Database) -> None:
    """A revision is what someone saw or approved. No later write may change that."""
    revision = CartRevision(samples.cart(), RevisionAuthor.AGENT, samples.NOW)
    with database.transaction():
        PostgresCartRevisionRepository(database).add(revision)

    for statement in (update(cart_revisions).values(author="x"), delete(cart_revisions)):
        with pytest.raises(DBAPIError, match="append only"), database.transaction():
            database.writer().execute(statement)

    assert PostgresCartRevisionRepository(database).for_cart("c_1") == [revision]


def test_carts_stored_before_revisions_get_revision_one(database: Database) -> None:
    """Live carts predate the revision log. Each needs revision 1 for a later change to build on."""
    with database.transaction():
        PostgresCartRepository(database).add(samples.cart())
        database.writer().execute(text(_migration("0011_cart_revisions").BACKFILL))

    (revision,) = PostgresCartRevisionRepository(database).for_cart("c_1")
    assert revision.cart == samples.cart()
    assert revision.author is RevisionAuthor.AGENT


def test_bodies_stored_before_revisions_load_as_revision_one(database: Database) -> None:
    """Rows written before revisions existed have no such key. They must still load."""
    with database.transaction():
        PostgresCartRepository(database).add(dataclasses.replace(samples.cart(), revision=2))
        PostgresOrderRepository(database).add(dataclasses.replace(samples.order(), revision=2))
        for table in (carts, orders):
            database.writer().execute(update(table).values(body=table.c.body.op("-")("revision")))

    cart = PostgresCartRepository(database).get("c_1")
    order = PostgresOrderRepository(database).get("o_1")

    assert cart is not None
    assert cart.revision == 1
    assert order is not None
    assert order.revision == 1


def test_bodies_hold_no_float_for_money(database: Database) -> None:
    """A float body would turn 0.10 into 0.1000000000000000055 on the next read."""
    with database.transaction():
        PostgresOrderRepository(database).add(samples.order())

    with database.transaction():
        body = database.writer().execute(select(orders.c.body)).scalar_one()

    assert _floats(body) == []
    assert body["total_ex_vat"] == "1010.00"
    assert body["lines"][0]["unit_price"] == "0.10"
    assert Decimal(body["lines"][0]["unit_price"]) == samples.SMALL_MONEY


def test_mandate_stored_before_the_switch_loads_with_automatic_orders_off(
    database: Database,
) -> None:
    """Rows written before the switch existed have no such key. They must fail closed."""
    repository = PostgresMandateRepository(database)
    with database.transaction():
        repository.add(samples.mandate())
        database.writer().execute(
            update(mandates).values(body=mandates.c.body.op("-")("can_auto_order")),
        )

    latest = repository.latest(samples.BUYER_ID)

    assert latest is not None
    assert latest.can_auto_order is False


def test_cart_stored_before_the_stock_facts_reruns_as_unconfirmed(database: Database) -> None:
    """Rows written before the stock check have no stock facts. The rerun must fail closed."""
    repository = PostgresCartRepository(database)
    with database.transaction():
        repository.add(samples.cart())
        database.writer().execute(
            text(
                "UPDATE carts SET body = jsonb_set(body, '{lines,0}', "
                "(body #> '{lines,0}') - 'stock_model' - 'available_qty' - 'needed_qty')"
            ),
        )

    loaded = repository.get("c_1")

    assert loaded is not None
    assert loaded.lines[0].stock_model is None


def test_racing_orders_for_one_cart_give_one_order(database: Database) -> None:
    """Checkout and approve can run at once on one cart; only one may place the order."""
    repository = PostgresOrderRepository(database)

    def place(index: int) -> None:
        with database.transaction():
            repository.add(samples.order(order_id=f"o_{index}", cart_id="c_1"))

    outcomes = _race(place)

    assert outcomes.count(None) == 1
    assert [type(error) for error in outcomes if error is not None] == [ValueError]
    assert repository.by_cart("c_1") is not None


def test_racing_mandate_edits_give_one_version(database: Database) -> None:
    """Two edits read the same latest version; only one may become the next one."""
    repository = PostgresMandateRepository(database)
    with database.transaction():
        repository.add(samples.mandate(version=1))

    def edit(_: int) -> None:
        with database.transaction():
            repository.add(samples.mandate(version=2))

    outcomes = _race(edit)

    assert outcomes.count(None) == 1
    assert [type(error) for error in outcomes if error is not None] == [ValueError]


def test_locked_cart_blocks_a_second_locker(database: Database) -> None:
    """Two reads after the deadline must not both expire the cart and write two records."""
    repository = PostgresCartRepository(database)
    with database.transaction():
        repository.add(samples.cart())
    outcome: list[BaseException] = []

    def lock_again() -> None:
        try:
            with database.transaction():
                database.writer().execute(text("SET LOCAL lock_timeout = '100ms'"))
                repository.get_locked("c_1")
        except DBAPIError as error:
            outcome.append(error)

    with database.transaction():
        repository.get_locked("c_1")
        other = threading.Thread(target=lock_again)
        other.start()
        other.join()

    assert len(outcome) == 1
    assert "lock" in str(outcome[0])


def test_day_lock_blocks_a_second_checkout_for_the_day(database: Database) -> None:
    """Two checkouts for one buyer and date must read the day's orders one after the other."""
    repository = PostgresOrderRepository(database)
    outcome: list[BaseException] = []

    def lock_again() -> None:
        try:
            with database.transaction():
                database.writer().execute(text("SET LOCAL lock_timeout = '100ms'"))
                repository.lock_days(samples.BUYER_ID, [samples.DELIVERY_DATE])
        except DBAPIError as error:
            outcome.append(error)

    with database.transaction():
        repository.lock_days(samples.BUYER_ID, [samples.DELIVERY_DATE])
        other = threading.Thread(target=lock_again)
        other.start()
        other.join()

    assert len(outcome) == 1
    assert "lock" in str(outcome[0])


def test_migrations_match_the_tables(database: Database) -> None:
    """A table change without a migration would pass the tests and break the deploy."""
    with database.transaction():
        context = MigrationContext.configure(database.writer())
        drift = compare_metadata(context, metadata)

    assert drift == []
