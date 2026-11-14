import dataclasses
from decimal import Decimal

from app.domain.agent_key import AgentKey, User, hash_agent_key
from app.domain.enums import AgentKeyStatus, AgentScope, Decision, UserRole
from app.domain.mandate import Mandate, RankingWeights
from app.services.ports.repositories import (
    AgentKeyRepository,
    MandateRepository,
    UserRepository,
)
from app.services.ports.unit_of_work import UnitOfWork

DEMO_BUYER_ID = "hotel-1"
DEMO_AGENT_ID = "claude-code"
DEMO_MAIN_USER_ID = "hotel-1-main"
_DEMO_AUTO_LIMIT = Decimal("500.00")


def seed_demo(
    mandates: MandateRepository,
    agent_keys: AgentKeyRepository,
    users: UserRepository,
    unit_of_work: UnitOfWork,
    agent_key: str,
) -> None:
    """Version 1 of the hotel 1 mandate, its agent and its main user.

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
