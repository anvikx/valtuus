from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Protocol

from app.domain.agent_key import AgentKey, User
from app.domain.audit import AuditRecord
from app.domain.cart import Cart, CartRevision
from app.domain.idempotency import IdempotencyRecord
from app.domain.mandate import Mandate
from app.domain.offer import Offer
from app.domain.order import Order
from app.domain.session import Session


class MandateRepository(Protocol):
    def latest(self, buyer_id: str) -> Mandate | None: ...

    def add(self, mandate: Mandate) -> None:
        """Refuses a version that is not the next one, so no version is lost or overwritten."""
        ...


class AgentKeyRepository(Protocol):
    def by_hash(self, key_hash: str) -> AgentKey | None: ...

    def for_buyer(self, buyer_id: str) -> Sequence[AgentKey]: ...

    def add(self, agent_key: AgentKey) -> None:
        """Adds a key, or replaces the key with the same hash (for example to revoke it)."""
        ...

    def mark_used(self, key_hash: str, at: datetime, cutoff: datetime) -> None:
        """Sets only last_used_at, and only when it is null or not after cutoff.

        A status change made since the read stays, and of two calls that read the same old time,
        only the first writes.
        """
        ...


class UserRepository(Protocol):
    def get(self, user_id: str) -> User | None: ...

    def add(self, user: User) -> None: ...


class SessionRepository(Protocol):
    def get(self, token_hash: str) -> Session | None: ...

    def add(self, session: Session) -> None: ...

    def remove(self, token_hash: str) -> None:
        """Does nothing for an unknown hash, so a second logout is not an error."""
        ...

    def remove_expired(self, now: datetime) -> None: ...


class OfferRepository(Protocol):
    def get(self, offer_id: str) -> Offer | None: ...

    def add(self, offer: Offer) -> None: ...


class CartRepository(Protocol):
    def get(self, cart_id: str) -> Cart | None: ...

    def for_buyer(self, buyer_id: str) -> Sequence[Cart]: ...

    def get_locked(self, cart_id: str) -> Cart | None:
        """Holds the cart row until the transaction ends, so two state changes cannot race."""
        ...

    def add(self, cart: Cart) -> None: ...

    def save(self, cart: Cart) -> None:
        """Stores a new state of a known cart. Lines and prices change only with a new revision."""
        ...


class CartRevisionRepository(Protocol):
    """Append only: a stored revision never changes."""

    def add(self, revision: CartRevision) -> None:
        """Refuses a revision number the cart already has."""
        ...

    def for_cart(self, cart_id: str) -> Sequence[CartRevision]:
        """The revisions of the cart, the first one first."""
        ...


class OrderRepository(Protocol):
    def get(self, order_id: str) -> Order | None: ...

    def by_cart(self, cart_id: str) -> Order | None: ...

    def for_day(self, buyer_id: str, delivery_date: date) -> Sequence[Order]: ...

    def lock_days(self, buyer_id: str, days: Iterable[date]) -> None:
        """Holds the buyer's delivery dates until the transaction ends.

        Two checkouts for one date then read the day's orders one after the other.
        """
        ...

    def add(self, order: Order) -> None:
        """Refuses a second order for the same cart."""
        ...


class AuditRepository(Protocol):
    """Append only: no update and no delete, by design."""

    def append(self, record: AuditRecord) -> None: ...

    def for_cart(
        self,
        cart_id: str,
        *,
        buyer_id: str | None = None,
        request_ids: Sequence[str] = (),
    ) -> Sequence[AuditRecord]:
        """Records of the cart and of the requests that led to it, in insert order.

        A request record joins only when it has this buyer_id. No buyer_id joins none.
        """
        ...


class IdempotencyRepository(Protocol):
    def get(self, buyer_id: str, key: str) -> IdempotencyRecord | None: ...

    def add(self, record: IdempotencyRecord) -> None:
        """Refuses a key the buyer used before, so two retries cannot both run."""
        ...
