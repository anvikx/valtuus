import anyio
import anyio.to_thread

from app.domain.cart import Cart
from app.domain.enums import CartState, Decision
from app.services.cart_service import CartDetails, CartService

# Under the 30 to 60 second read timeouts of common MCP and HTTP clients, so the reply arrives.
HOLD_SECONDS = 25.0
# A phone tap reaches the agent within one read.
READ_SECONDS = 1.0
# Waits read in their own small pool, so many waiting agents never take the threads that the
# REST routes and the other tools need.
READ_SLOTS = 4
# Holds at the same time. Over the cap a wait reads once and returns, as get_cart does, so the
# read queue stays short enough for every reply to come inside the hold.
MAX_HOLDS = 32


class DecisionWaiter:
    """Holds an agent's cart read until the main user decides, so the agent needs no timer.

    ponytail: reads the cart every READ_SECONDS, with one cap for all buyers. Use Postgres
    LISTEN/NOTIFY and a cap per agent key when many agents wait at the same time.
    """

    def __init__(
        self,
        carts: CartService,
        hold_seconds: float = HOLD_SECONDS,
        read_seconds: float = READ_SECONDS,
        max_holds: int = MAX_HOLDS,
    ) -> None:
        self._carts = carts
        self._hold_seconds = hold_seconds
        self._read_seconds = read_seconds
        self._read_slots = anyio.CapacityLimiter(READ_SLOTS)
        self._holds = anyio.CapacityLimiter(max_holds)

    async def wait(self, buyer_id: str, cart_id: str, revision: int) -> CartDetails:
        """The cart when the agent can act on it, or the pending cart after the hold.

        A monotonic timer, not the gateway clock: DEMO_NOW freezes that clock.
        """
        try:
            self._holds.acquire_nowait()
        except anyio.WouldBlock:
            return await self._read(buyer_id, cart_id)

        try:
            return await self._hold(buyer_id, cart_id, revision)
        finally:
            self._holds.release()

    async def _hold(self, buyer_id: str, cart_id: str, revision: int) -> CartDetails:
        give_up_at = anyio.current_time() + self._hold_seconds
        while True:
            details = await self._read(buyer_id, cart_id)
            if _can_act(details.cart, revision) or anyio.current_time() >= give_up_at:
                return details

            await anyio.sleep(self._read_seconds)

    async def _read(self, buyer_id: str, cart_id: str) -> CartDetails:
        return await anyio.to_thread.run_sync(
            self._carts.get_cart_details,
            buyer_id,
            cart_id,
            limiter=self._read_slots,
        )


def _can_act(cart: Cart, revision: int) -> bool:
    # get_cart sets EXPIRED once approve_before passes, so a dead deadline also ends the wait.
    return (
        cart.state is not CartState.PENDING_APPROVAL
        or cart.revision != revision
        or cart.current_decision is Decision.AUTO
    )
