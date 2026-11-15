import dataclasses
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.domain.agent_key import AgentKey, User, hash_agent_key
from app.domain.constants import CURRENCY, GATEWAY_TIMEZONE
from app.domain.enums import AgentKeyStatus, AgentScope, Decision, UserRole
from app.domain.mandate import Mandate, RankingWeights
from app.domain.order import Order, OrderLine
from app.services.offer_service import ISSUER
from app.services.ports.repositories import (
    AgentKeyRepository,
    MandateRepository,
    OrderRepository,
    UserRepository,
)
from app.services.ports.unit_of_work import UnitOfWork

DEMO_BUYER_ID = "hotel-1"
DEMO_AGENT_ID = "claude-code"
DEMO_MAIN_USER_ID = "hotel-1-main"
_DEMO_AUTO_LIMIT = Decimal("500.00")

# Approved past orders of the demo milk, so run 2 is a known product on a fresh store.
_HISTORY_PRODUCT_ID = "464306"
_HISTORY_GTIN = "6408430000487"
_HISTORY_NAME = "Valio Hyvä suomalainen Arki® Eila® semi skimmed milk drink 1 l lactose free"
_HISTORY_UNIT_PRICE = Decimal("1.01")
_HISTORY_QTY = 200
# Mondays. Each order is placed on the Thursday before.
_HISTORY_DELIVERY_DATES = (date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9))
_HISTORY_LEAD = timedelta(days=4)
_HISTORY_PLACED_TIME = time(10, 0)


def seed_demo(
    mandates: MandateRepository,
    agent_keys: AgentKeyRepository,
    users: UserRepository,
    unit_of_work: UnitOfWork,
    agent_key: str,
    orders: OrderRepository,
) -> None:
    """Version 1 of the hotel 1 mandate, its agent, its main user and its order history.

    Runs on every start. It adds only what is missing, so a restart on a lasting store
    keeps a newer mandate and does not make a revoked key active again.
    """
    # An empty key would match any request that sends an empty key.
    if not agent_key:
        raise ValueError("the demo agent key is empty")

    with unit_of_work.transaction():
        if mandates.latest(DEMO_BUYER_ID) is None:
            mandates.add(_demo_mandate())

        _seed_agent_key(agent_keys, hash_agent_key(agent_key))

        if users.get(DEMO_MAIN_USER_ID) is None:
            users.add(
                User(
                    user_id=DEMO_MAIN_USER_ID,
                    buyer_id=DEMO_BUYER_ID,
                    role=UserRole.MAIN_USER,
                ),
            )

        _seed_history(orders)


def _demo_mandate() -> Mandate:
    return Mandate(
        buyer_id=DEMO_BUYER_ID,
        version=1,
        max_auto_order_value=_DEMO_AUTO_LIMIT,
        max_auto_value_per_delivery_date=_DEMO_AUTO_LIMIT,
        max_line_value=None,
        required_attributes=(),
        forbidden_allergens=(),
        allergen_unknown_policy=Decision.HUMAN,
        preferred_brands=(),
        ranking_weights=RankingWeights(price=1.0, reliability=0.0, co2=0.0),
    )


def _seed_history(orders: OrderRepository) -> None:
    # Fixed ids, so a restart finds the orders and does not add them a second time.
    for number, delivery_date in enumerate(_HISTORY_DELIVERY_DATES, start=1):
        order_id = f"ord_seed_{number}"
        if orders.get(order_id) is None:
            orders.add(_history_order(order_id, f"c_seed_{number}", delivery_date))


def _history_order(order_id: str, cart_id: str, delivery_date: date) -> Order:
    total = _HISTORY_UNIT_PRICE * _HISTORY_QTY
    placed_on = delivery_date - _HISTORY_LEAD
    return Order(
        order_id=order_id,
        cart_id=cart_id,
        buyer_id=DEMO_BUYER_ID,
        lines=(
            OrderLine(
                product_id=_HISTORY_PRODUCT_ID,
                gtin=_HISTORY_GTIN,
                name=_HISTORY_NAME,
                qty=_HISTORY_QTY,
                unit_price=_HISTORY_UNIT_PRICE,
                line_total=total,
                delivery_date=delivery_date,
                substitute_for=None,
            ),
        ),
        total_ex_vat=total,
        currency=CURRENCY,
        placed_at=datetime.combine(placed_on, _HISTORY_PLACED_TIME, GATEWAY_TIMEZONE),
        placed_by=f"{DEMO_AGENT_ID} (agent)",
        approved_by=DEMO_MAIN_USER_ID,
        offer_ids=(),
        mandate_version=1,
        issuer=ISSUER,
        signature=None,
    )


def _seed_agent_key(agent_keys: AgentKeyRepository, key_hash: str) -> None:
    # A new AGENT_KEY in .env replaces the old one, so the old key must stop working.
    for old in agent_keys.for_buyer(DEMO_BUYER_ID):
        is_replaced = old.agent_id == DEMO_AGENT_ID and old.key_hash != key_hash
        if is_replaced and old.status is AgentKeyStatus.ACTIVE:
            agent_keys.add(dataclasses.replace(old, status=AgentKeyStatus.REVOKED))

    if agent_keys.by_hash(key_hash) is not None:
        return

    agent_keys.add(
        AgentKey(
            agent_id=DEMO_AGENT_ID,
            agent_name=DEMO_AGENT_ID,
            buyer_id=DEMO_BUYER_ID,
            key_hash=key_hash,
            scopes=frozenset(AgentScope),
            status=AgentKeyStatus.ACTIVE,
        ),
    )
