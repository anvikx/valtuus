"""Domain objects with every nested type filled, so a round trip covers the whole codec."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.agent_key import AgentKey, hash_agent_key
from app.domain.audit import AuditRecord
from app.domain.cart import Cart, CartLine
from app.domain.catalog import Allergens, SearchQuery
from app.domain.enums import (
    AgentKeyStatus,
    AgentScope,
    AllergenStatus,
    AllergenType,
    AuditStep,
    CartState,
    Decision,
    FlowPhase,
    OfferTier,
    ReasonCode,
    StockModel,
    SubstituteBasis,
    Unit,
)
from app.domain.mandate import Mandate, RankingWeights
from app.domain.offer import (
    ComparisonPrice,
    Offer,
    OfferLine,
    ProposedSplit,
    RejectedProduct,
    RequestedItem,
    SplitLine,
    SubstituteFor,
)
from app.domain.order import Order, OrderLine

BUYER_ID = "hotel-1"
DELIVERY_DATE = date(2026, 11, 20)
NOW = datetime(2026, 11, 14, 9, 30, tzinfo=UTC)
# A float would turn 0.10 into 0.1000000000000000055 and drop the trailing zeros.
SMALL_MONEY = Decimal("0.10")
LARGE_MONEY = Decimal("1010.00")

_SUBSTITUTE = SubstituteFor(
    product_id="p_1",
    name="Milk 1 l",
    basis=SubstituteBasis.SAME_CATEGORY,
    reason_code=ReasonCode.SUBSTITUTE_FOR_REQUESTED,
    reason_sentence="The requested milk is sold out.",
    price_difference_per_unit=SMALL_MONEY,
)


def mandate(version: int = 1) -> Mandate:
    return Mandate(
        buyer_id=BUYER_ID,
        version=version,
        max_auto_order_value=LARGE_MONEY,
        max_auto_value_per_delivery_date=LARGE_MONEY,
        max_line_value=SMALL_MONEY,
        required_attributes=("lactose_free",),
        forbidden_allergens=("nuts",),
        allergen_unknown_policy=Decision.HUMAN,
        preferred_brands=("Valio",),
        ranking_weights=RankingWeights(price=0.5, reliability=0.3, co2=0.2),
        can_auto_order=True,
    )


def agent_key(key: str = "key-1", buyer_id: str = BUYER_ID) -> AgentKey:
    return AgentKey(
        agent_id="claude-code",
        agent_name="Claude Code",
        buyer_id=buyer_id,
        key_hash=hash_agent_key(key),
        scopes=frozenset({AgentScope.CART, AgentScope.CHECKOUT}),
        status=AgentKeyStatus.ACTIVE,
        last_used_at=NOW,
    )


def offer(offer_id: str = "of_1") -> Offer:
    line = OfferLine(
        rank=1,
        tier=OfferTier.BEST,
        product_id="p_2",
        gtin="6408430000012",
        name="Oat milk 1 l",
        brand="Valio",
        country_of_origin="FI",
        labels=("organic",),
        allergens=Allergens(
            status=AllergenStatus.KNOWN,
            declarations={AllergenType.CONTAINS: ("oats",)},
            free_from=("milk",),
        ),
        delivery_reliability=Decimal("0.97"),
        co2_kg_per_kg=None,
        sales_units_needed=2,
        unit_price=SMALL_MONEY,
        currency="EUR",
        vat_rate=Decimal("14.0"),
        comparison_price=ComparisonPrice(value=SMALL_MONEY, per=Unit.L),
        price_valid_from=DELIVERY_DATE,
        price_valid_to=DELIVERY_DATE,
        stock_model=StockModel.STOCK,
        available_qty=None,
        available_date=DELIVERY_DATE,
        closing_time=NOW,
        line_total=LARGE_MONEY,
        max_auto_qty=10,
        substitute_for=_SUBSTITUTE,
        reason_codes=(ReasonCode.SUBSTITUTE_FOR_REQUESTED,),
        reason_sentences=("Oat milk replaces milk.",),
    )
    return Offer(
        offer_id=offer_id,
        buyer_id=BUYER_ID,
        issuer="valtuus",
        issued_at=NOW,
        source_time=NOW,
        valid_until=NOW,
        requested=RequestedItem(quantity=Decimal("2.5"), unit=Unit.L, deliver_by=None),
        lines=(line,),
        proposed_split=ProposedSplit(
            lines=(SplitLine(product_id="p_2", qty=2, reason_codes=()),),
            unfilled_qty=0,
        ),
        rejected=(
            RejectedProduct(
                product_id="p_3",
                name="Cream",
                reason_code=ReasonCode.NO_PRICE,
                reason_sentence="No price.",
                closing_time=None,
            ),
        ),
        signature=None,
        request_id="r_1",
    )


def cart(
    cart_id: str = "c_1",
    state: CartState = CartState.PENDING_APPROVAL,
) -> Cart:
    line = CartLine(
        offer_id="of_1",
        product_id="p_2",
        name="Oat milk 1 l",
        qty=2,
        unit_price=SMALL_MONEY,
        line_total=LARGE_MONEY,
        delivery_date=DELIVERY_DATE,
        closing_time=NOW,
        decision=Decision.HUMAN,
        substitute_for=_SUBSTITUTE,
        reason_codes=(ReasonCode.OVER_AUTO_LIMIT,),
        reason_sentences=("Over the limit.",),
    )
    return Cart(
        cart_id=cart_id,
        buyer_id=BUYER_ID,
        agent_name="Claude Code",
        state=state,
        decision=Decision.HUMAN,
        reason_codes=(ReasonCode.OVER_AUTO_LIMIT,),
        reason_sentences=("Over the limit.",),
        current_decision=Decision.HUMAN,
        current_reason_codes=(ReasonCode.OVER_AUTO_LIMIT,),
        request_text="2 l oat milk",
        clarifications=(),
        interpreted_request=SearchQuery(
            query="oat milk",
            required_attributes=(),
            quantity=Decimal("2"),
            unit=Unit.L,
            deliver_by=DELIVERY_DATE,
            preferred_brands=(),
        ),
        lines=(line,),
        total_ex_vat=LARGE_MONEY,
        currency="EUR",
        mandate_version=1,
        valid_until=NOW,
        approve_before=NOW,
        duplicate_of_order_id=None,
        delivery_day_total_ex_vat=LARGE_MONEY,
        order_id=None,
        previous_reject_reason=None,
        decided_by=None,
        decided_at=None,
        reject_reason=None,
    )


def order(
    order_id: str = "o_1",
    cart_id: str = "c_1",
    delivery_date: date = DELIVERY_DATE,
) -> Order:
    line = OrderLine(
        product_id="p_2",
        gtin="6408430000012",
        name="Oat milk 1 l",
        qty=2,
        unit_price=SMALL_MONEY,
        line_total=LARGE_MONEY,
        delivery_date=delivery_date,
        substitute_for=_SUBSTITUTE,
    )
    return Order(
        order_id=order_id,
        cart_id=cart_id,
        buyer_id=BUYER_ID,
        lines=(line,),
        total_ex_vat=LARGE_MONEY,
        currency="EUR",
        placed_at=NOW,
        placed_by="claude-code",
        approved_by="hotel-1-main",
        offer_ids=("of_1",),
        mandate_version=1,
        issuer="valtuus",
        signature=None,
    )


def audit_record(
    record_id: str,
    cart_id: str | None = "c_1",
    request_id: str | None = "r_1",
    buyer_id: str | None = BUYER_ID,
) -> AuditRecord:
    return AuditRecord(
        record_id=record_id,
        cart_id=cart_id,
        request_id=request_id,
        step=AuditStep.POLICY,
        phase=FlowPhase.ORDER,
        actor="claude-code",
        input_data={"total": "1010.00", "lines": [1, 2]},
        output_data={"decision": "HUMAN"},
        decision=Decision.HUMAN,
        reason_codes=(ReasonCode.OVER_AUTO_LIMIT,),
        mandate_version=1,
        sentence="Over the limit.",
        created_at=NOW,
        buyer_id=buyer_id,
    )
