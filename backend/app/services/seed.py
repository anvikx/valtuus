from decimal import Decimal

from app.domain.access import AgentKey, User, hash_agent_key
from app.domain.enums import AgentKeyStatus, AgentScope, Decision, UserRole
from app.domain.mandate import Mandate, RankingWeights
from app.services.ports.repositories import (
    AgentKeyRepository,
    MandateRepository,
    UserRepository,
)

DEMO_BUYER_ID = "hotel-1"
DEMO_AGENT_ID = "claude-code"
DEMO_MAIN_USER_ID = "hotel-1-main"
_DEMO_AUTO_LIMIT = Decimal("500.00")


def seed_demo(
    mandates: MandateRepository,
    agent_keys: AgentKeyRepository,
    users: UserRepository,
    agent_key: str,
) -> None:
    """Version 1 of the hotel 1 mandate, its agent and its main user."""
    # An empty key would match any request that sends an empty key.
    if not agent_key:
        raise ValueError("the demo agent key is empty")

    mandates.add(
        Mandate(
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
        ),
    )
    agent_keys.add(
        AgentKey(
            agent_id=DEMO_AGENT_ID,
            agent_name=DEMO_AGENT_ID,
            buyer_id=DEMO_BUYER_ID,
            key_hash=hash_agent_key(agent_key),
            scopes=frozenset(AgentScope),
            status=AgentKeyStatus.ACTIVE,
        ),
    )
    users.add(
        User(
            user_id=DEMO_MAIN_USER_ID,
            buyer_id=DEMO_BUYER_ID,
            role=UserRole.MAIN_USER,
        ),
    )
