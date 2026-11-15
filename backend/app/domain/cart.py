from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from app.domain.catalog import SearchQuery
from app.domain.enums import CartState, Decision, ReasonCode, RevisionAuthor, StockModel
from app.domain.offer import SubstituteFor

# Checkout and approve act only on these. Every other state is final.
OPEN_STATES = frozenset({CartState.AUTO, CartState.PENDING_APPROVAL})
STATE_BY_DECISION = MappingProxyType(
    {
        Decision.AUTO: CartState.AUTO,
        Decision.HUMAN: CartState.PENDING_APPROVAL,
        Decision.DENY: CartState.DENIED,
    }
)


@dataclass(frozen=True)
class CartLineInput:
    """What the agent may send for a line. Price, stock and date come from the stored offer."""

    offer_id: str
    product_id: str
    qty: int


@dataclass(frozen=True)
class CartDraft:
    lines: tuple[CartLineInput, ...]
    request_text: str
    clarifications: tuple[str, ...]


@dataclass(frozen=True)
class PricedLine:
    """A draft line with its price and dates from the stored offer, before the policy runs."""

    offer_id: str
    product_id: str
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    closing_time: datetime
    substitute_for: SubstituteFor | None
    # The offer line's stock, so the policy sees it at create, checkout and approve.
    stock_model: StockModel | None
    available_qty: int | None
    needed_qty: int


@dataclass(frozen=True)
class CartLine:
    offer_id: str
    product_id: str
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    closing_time: datetime
    decision: Decision
    substitute_for: SubstituteFor | None
    reason_codes: tuple[ReasonCode, ...]
    reason_sentences: tuple[str, ...]
    # Defaults for carts stored before the stock check: the rerun reads them as unconfirmed.
    stock_model: StockModel | None = None
    available_qty: int | None = None
    needed_qty: int = 0


@dataclass(frozen=True)
class LineChange:
    """A product whose quantity differs between two revisions. None: not in that revision."""

    product_id: str
    name: str
    qty_before: int | None
    qty_after: int | None


@dataclass(frozen=True)
class Cart:
    """The lines of one revision never change. A change of lines makes the next revision."""

    cart_id: str
    buyer_id: str
    agent_name: str
    state: CartState
    decision: Decision
    reason_codes: tuple[ReasonCode, ...]
    reason_sentences: tuple[str, ...]
    current_decision: Decision
    current_reason_codes: tuple[ReasonCode, ...]
    request_text: str
    clarifications: tuple[str, ...]
    interpreted_request: SearchQuery | None
    lines: tuple[CartLine, ...]
    total_ex_vat: Decimal
    currency: str
    mandate_version: int
    valid_until: datetime
    approve_before: datetime
    duplicate_of_order_id: str | None
    delivery_day_total_ex_vat: Decimal
    order_id: str | None
    previous_reject_reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    reject_reason: str | None
    # A body stored before revisions existed loads as the first one.
    revision: int = 1
    # None only for snapshots written before revision deltas were stored.
    changes: tuple[LineChange, ...] | None = None


@dataclass(frozen=True)
class CartRevision:
    """One stored version of a cart. Its id and number come from the cart snapshot."""

    cart: Cart
    author: RevisionAuthor
    created_at: datetime


def cart_changes(
    before: Iterable[CartLine],
    after: Iterable[CartLine],
) -> tuple[LineChange, ...]:
    """By product id, so a new offer or price for the same quantity is no change.

    The lines of the newer revision come first, in their order, then the removed lines.
    """
    old = {line.product_id: line for line in before}
    new = {line.product_id: line for line in after}
    kept_or_added = [
        LineChange(line.product_id, line.name, _qty(old.get(product_id)), line.qty)
        for product_id, line in new.items()
        if _qty(old.get(product_id)) != line.qty
    ]
    removed = [
        LineChange(line.product_id, line.name, line.qty, None)
        for product_id, line in old.items()
        if product_id not in new
    ]
    return (*kept_or_added, *removed)


def _qty(line: CartLine | None) -> int | None:
    return None if line is None else line.qty
