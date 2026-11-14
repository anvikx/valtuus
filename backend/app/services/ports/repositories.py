from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from app.domain.agent_key import AgentKey, User
from app.domain.audit import AuditRecord
from app.domain.cart import Cart
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

    def add(self, cart: Cart) -> None: ...

    def save(self, cart: Cart) -> None:
        """Stores a new state of a known cart. Lines and prices must not change."""
        ...


class OrderRepository(Protocol):
    def get(self, order_id: str) -> Order | None: ...

    def by_cart(self, cart_id: str) -> Order | None: ...

    def for_day(self, buyer_id: str, delivery_date: date) -> Sequence[Order]: ...

    def add(self, order: Order) -> None:
        """Refuses a second order for the same cart."""
        ...


class AuditRepository(Protocol):
    """Append only: no update and no delete, by design."""

    def append(self, record: AuditRecord) -> None: ...

    def for_cart(self, cart_id: str) -> Sequence[AuditRecord]: ...


class IdempotencyRepository(Protocol):
    def get(self, buyer_id: str, key: str) -> IdempotencyRecord | None: ...

    def add(self, record: IdempotencyRecord) -> None:
        """Refuses a key the buyer used before, so two retries cannot both run."""
        ...
