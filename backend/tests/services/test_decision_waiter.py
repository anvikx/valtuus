import dataclasses

import anyio
import pytest

from app.domain.enums import CartState, Decision
from app.services.decision_waiter import DecisionWaiter
from tests.services.test_approval_service import _MAIN_USER, _REASON, _World

# Short times keep the test fast. A whole hold is far longer than one read.
_HOLD_SECONDS = 0.5
_READ_SECONDS = 0.01


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _waiting_world(state: CartState = CartState.PENDING_APPROVAL) -> _World:
    """A cart the agent cannot order yet: the current mandate does not make it AUTO."""
    world = _World(state=state)
    world.deny.is_on = True
    return world


def _waiter(world: _World, max_holds: int = 1) -> DecisionWaiter:
    return DecisionWaiter(world.cart_service, _HOLD_SECONDS, _READ_SECONDS, max_holds)


async def _wait(world: _World, revision: int | None = None) -> tuple[CartState, float]:
    started = anyio.current_time()
    details = await _waiter(world).wait(
        world.cart.buyer_id,
        world.cart.cart_id,
        world.cart.revision if revision is None else revision,
    )
    return details.cart.state, anyio.current_time() - started


@pytest.mark.anyio
async def test_reject_during_the_wait_returns_at_once():
    """The agent must tell the buyer about the main user's decision without waiting the hold."""
    world = _waiting_world()

    async def reject_soon() -> None:
        await anyio.sleep(_READ_SECONDS * 3)
        world.service.reject(_MAIN_USER, world.cart.cart_id, world.cart.revision, _REASON)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(reject_soon)
        state, waited = await _wait(world)

    assert state is CartState.REJECTED
    assert waited < _HOLD_SECONDS


@pytest.mark.anyio
async def test_no_decision_returns_the_pending_cart_after_the_hold():
    """A hold with no end would pass the client timeout, and the agent would lose the reply."""
    world = _waiting_world()

    state, waited = await _wait(world)

    assert state is CartState.PENDING_APPROVAL
    assert waited >= _HOLD_SECONDS


@pytest.mark.anyio
async def test_changed_revision_returns_at_once():
    """The main user changed the lines, so the agent must read them before it waits again."""
    world = _waiting_world()
    world.carts.save(dataclasses.replace(world.cart, revision=world.cart.revision + 1))

    state, waited = await _wait(world, revision=world.cart.revision)

    assert state is CartState.PENDING_APPROVAL
    assert waited < _HOLD_SECONDS


@pytest.mark.anyio
async def test_cart_that_is_not_pending_returns_at_once():
    """There is nothing to wait for, so holding would only delay the agent."""
    world = _waiting_world(CartState.AUTO)

    state, waited = await _wait(world)

    assert state is CartState.AUTO
    assert waited < _HOLD_SECONDS


@pytest.mark.anyio
async def test_mandate_that_now_allows_the_cart_returns_at_once():
    """The main user widened the rules, so the agent can check out without an approve."""
    world = _waiting_world()

    async def allow_soon() -> None:
        await anyio.sleep(_READ_SECONDS * 3)
        world.deny.is_on = False

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(allow_soon)
        started = anyio.current_time()
        details = await _waiter(world).wait(
            world.cart.buyer_id, world.cart.cart_id, world.cart.revision
        )

    assert details.cart.state is CartState.PENDING_APPROVAL
    assert details.cart.current_decision is Decision.AUTO
    assert anyio.current_time() - started < _HOLD_SECONDS


@pytest.mark.anyio
async def test_deadline_passed_returns_the_expired_cart():
    """After approve_before nobody can approve, so the agent must stop waiting."""
    world = _waiting_world()
    world.clock.at = world.cart.approve_before

    state, waited = await _wait(world)

    assert state is CartState.EXPIRED
    assert waited < _HOLD_SECONDS


@pytest.mark.anyio
async def test_wait_over_the_cap_reads_once_and_returns():
    """Unbounded holds would queue reads past the client timeout for every waiting buyer."""
    world = _waiting_world()
    waiter = _waiter(world, max_holds=1)
    args = (world.cart.buyer_id, world.cart.cart_id, world.cart.revision)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(waiter.wait, *args)
        await anyio.sleep(_READ_SECONDS)
        started = anyio.current_time()
        details = await waiter.wait(*args)
        over_cap = anyio.current_time() - started

    assert details.cart.state is CartState.PENDING_APPROVAL
    assert over_cap < _HOLD_SECONDS
