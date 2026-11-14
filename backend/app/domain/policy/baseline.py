from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from app.domain.order import Order


@dataclass(frozen=True)
class ProductBaseline:
    confirmed_count: int
    max_confirmed_quantity: int
    last_confirmed_unit_price: Decimal
    last_confirmed_at: datetime


def build_baseline(orders: Iterable[Order]) -> Mapping[str, ProductBaseline]:
    """Automatic orders must never increase what an agent is allowed to repeat."""
    baseline: dict[str, ProductBaseline] = {}
    for order in sorted(orders, key=lambda item: (item.placed_at, item.order_id)):
        if order.approved_by is None:
            continue

        for line in order.lines:
            previous = baseline.get(line.product_id)
            baseline[line.product_id] = ProductBaseline(
                confirmed_count=1 if previous is None else previous.confirmed_count + 1,
                max_confirmed_quantity=max(
                    line.qty,
                    0 if previous is None else previous.max_confirmed_quantity,
                ),
                last_confirmed_unit_price=line.unit_price,
                last_confirmed_at=order.placed_at,
            )

    return MappingProxyType(baseline)
