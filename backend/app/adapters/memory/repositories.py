import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime

from app.domain.agent_key import AgentKey, User
from app.domain.audit import AuditRecord
from app.domain.cart import Cart, CartRevision
from app.domain.idempotency import IdempotencyRecord
from app.domain.mandate import Mandate
from app.domain.offer import Offer
from app.domain.order import Order
from app.domain.session import Session


class InMemoryMandateRepository:
    def __init__(self) -> None:
        self._versions: dict[str, list[Mandate]] = {}
        # Sync routes run in a thread pool; two edits must not both become version N.
        self._lock = threading.Lock()

    def latest(self, buyer_id: str) -> Mandate | None:
        versions = self._versions.get(buyer_id)
        return versions[-1] if versions else None

    def add(self, mandate: Mandate) -> None:
        with self._lock:
            versions = self._versions.setdefault(mandate.buyer_id, [])
            expected = len(versions) + 1
            if mandate.version != expected:
                raise ValueError(f"mandate version must be {expected}, got {mandate.version}")
            versions.append(mandate)


class InMemoryAgentKeyRepository:
    def __init__(self) -> None:
        self._by_hash: dict[str, AgentKey] = {}

    def by_hash(self, key_hash: str) -> AgentKey | None:
        return self._by_hash.get(key_hash)

    def for_buyer(self, buyer_id: str) -> Sequence[AgentKey]:
        return [key for key in self._by_hash.values() if key.buyer_id == buyer_id]

    def add(self, agent_key: AgentKey) -> None:
        self._by_hash[agent_key.key_hash] = agent_key


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def add(self, user: User) -> None:
        self._by_id[user.user_id] = user


class InMemoryOfferRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Offer] = {}

    def get(self, offer_id: str) -> Offer | None:
        return self._by_id.get(offer_id)

    def add(self, offer: Offer) -> None:
        self._by_id[offer.offer_id] = offer


class InMemoryCartRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Cart] = {}

    def get(self, cart_id: str) -> Cart | None:
        return self._by_id.get(cart_id)

    def for_buyer(self, buyer_id: str) -> Sequence[Cart]:
        return [cart for cart in self._by_id.values() if cart.buyer_id == buyer_id]

    def get_locked(self, cart_id: str) -> Cart | None:
        # The unit of work lock already serializes every transaction here.
        return self.get(cart_id)

    def add(self, cart: Cart) -> None:
        if cart.cart_id in self._by_id:
            raise ValueError(f"cart {cart.cart_id} exists")
        self._by_id[cart.cart_id] = cart

    def save(self, cart: Cart) -> None:
        if cart.cart_id not in self._by_id:
            raise ValueError(f"cart {cart.cart_id} is unknown")
        self._by_id[cart.cart_id] = cart


class InMemoryCartRevisionRepository:
    def __init__(self) -> None:
        self._by_cart: dict[str, dict[int, CartRevision]] = {}

    def add(self, revision: CartRevision) -> None:
        revisions = self._by_cart.setdefault(revision.cart.cart_id, {})
        if revision.cart.revision in revisions:
            raise ValueError(
                f"cart {revision.cart.cart_id} revision {revision.cart.revision} exists"
            )
        revisions[revision.cart.revision] = revision

    def for_cart(self, cart_id: str) -> Sequence[CartRevision]:
        revisions = self._by_cart.get(cart_id, {})
        return [revisions[number] for number in sorted(revisions)]


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, Order] = {}
        self._by_cart: dict[str, Order] = {}
        # Checkout and approve can race on one cart; only one of them may place the order.
        self._lock = threading.Lock()

    def get(self, order_id: str) -> Order | None:
        return self._by_id.get(order_id)

    def by_cart(self, cart_id: str) -> Order | None:
        return self._by_cart.get(cart_id)

    def for_day(self, buyer_id: str, delivery_date: date) -> Sequence[Order]:
        return [
            order
            for order in self._by_id.values()
            if order.buyer_id == buyer_id
            and any(line.delivery_date == delivery_date for line in order.lines)
        ]

    def lock_days(self, buyer_id: str, days: Iterable[date]) -> None:
        # The unit of work lock already serializes every transaction here.
        pass

    def add(self, order: Order) -> None:
        with self._lock:
            if order.cart_id in self._by_cart:
                raise ValueError(f"cart {order.cart_id} has an order")
            self._by_id[order.order_id] = order
            self._by_cart[order.cart_id] = order


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self._records.append(record)

    def for_cart(
        self,
        cart_id: str,
        *,
        buyer_id: str | None = None,
        request_ids: Sequence[str] = (),
    ) -> Sequence[AuditRecord]:
        def linked(record: AuditRecord) -> bool:
            return (
                buyer_id is not None
                and record.buyer_id == buyer_id
                and record.request_id in request_ids
            )

        return [record for record in self._records if record.cart_id == cart_id or linked(record)]


class InMemoryIdempotencyRepository:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def get(self, buyer_id: str, key: str) -> IdempotencyRecord | None:
        return self._by_key.get((buyer_id, key))

    def add(self, record: IdempotencyRecord) -> None:
        with self._lock:
            slot = (record.buyer_id, record.key)
            if slot in self._by_key:
                raise ValueError(f"idempotency key {record.key} is used")
            self._by_key[slot] = record


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._by_hash: dict[str, Session] = {}
        # Routes run in a thread pool, and the prune walks the dict while a login adds to it.
        self._lock = threading.Lock()

    def get(self, token_hash: str) -> Session | None:
        return self._by_hash.get(token_hash)

    def add(self, session: Session) -> None:
        with self._lock:
            self._by_hash[session.token_hash] = session

    def remove(self, token_hash: str) -> None:
        with self._lock:
            self._by_hash.pop(token_hash, None)

    def remove_expired(self, now: datetime) -> None:
        with self._lock:
            self._by_hash = {
                token_hash: session
                for token_hash, session in self._by_hash.items()
                if session.is_live(now)
            }


class InMemoryUnitOfWork:
    def __init__(self) -> None:
        # ponytail: one global lock serializes every write, and nothing rolls back.
        # Tests and local dev only; the Postgres store has real transactions.
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            yield
