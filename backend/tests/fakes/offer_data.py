"""Run 1 data (14 Nov 2026) and fakes for the catalog and the Valio Aimo price source."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from app.domain.catalog import Allergens, ContentPerSalesUnit, Product
from app.domain.constants import GATEWAY_TIMEZONE
from app.domain.enums import AllergenStatus, AllergenType, StockModel, Unit
from app.domain.errors import GatewayError
from app.domain.offer import Availability, AvailabilitySnapshot, OfferQuery, Price

MONDAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 14, 15, 39, tzinfo=GATEWAY_TIMEZONE)
SOURCE_TIME = datetime(2026, 11, 14, 15, 38, 58, tzinfo=GATEWAY_TIMEZONE)
CLOSING = datetime(2026, 11, 15, 17, tzinfo=GATEWAY_TIMEZONE)
PRICE_END = date(2026, 12, 31)
# The mock's amount for a stocked product with no known count.
UNKNOWN_AMOUNT = 9_999_999_999
MILK_ID = "464306"
ONE_LITRE = ContentPerSalesUnit(Decimal(1), Unit.L)


def product(
    product_id: str = MILK_ID,
    *,
    sales_unit: str = "ST",
    content: ContentPerSalesUnit | None = ONE_LITRE,
    lot_size: Decimal | None = None,
) -> Product:
    return Product(
        product_id=product_id,
        gtin="6408430000012",
        name=f"Milk {product_id}",
        names={},
        brand="Valio",
        category="10400",
        sales_unit=sales_unit,
        content_per_sales_unit=content,
        attributes=(),
        allergens=Allergens(
            status=AllergenStatus.KNOWN,
            free_from=(),
            declarations={AllergenType.CONTAINS: ("AM",)},
        ),
        country_of_origin="FI",
        labels=(),
        substitute_ids=(),
        delivery_reliability=None,
        co2_kg_per_kg=None,
        lot_size=lot_size,
    )


def price(product_id: str = MILK_ID, unit_price: str = "1.01", valid_to: date = PRICE_END) -> Price:
    return Price(
        product_id=product_id,
        unit_price=Decimal(unit_price),
        vat_rate=Decimal("13.5"),
        comparison_price=None,
        valid_from=date(2026, 9, 1),
        valid_to=valid_to,
    )


def stock(
    product_id: str = MILK_ID,
    *,
    amount: int | None = UNKNOWN_AMOUNT,
    model: StockModel | None = StockModel.STOCK,
    available_date: date | None = MONDAY,
    sales_unit: str | None = "ST",
) -> Availability:
    return Availability(
        product_id=product_id,
        stock_model=model,
        amount=amount,
        available_date=available_date,
        closing_time=CLOSING,
        is_sales_blocked=False,
        sales_unit=sales_unit,
    )


def query(
    *product_ids: str,
    quantity: str | None = "1000",
    unit: Unit | None = Unit.L,
    deliver_by: date | None = MONDAY,
) -> OfferQuery:
    return OfferQuery(
        product_ids=product_ids or (MILK_ID,),
        quantity=None if quantity is None else Decimal(quantity),
        unit=unit,
        deliver_by=deliver_by,
        preferred_brands=(),
        include_substitutes=False,
    )


class FakeCatalog:
    def __init__(self, *products: Product) -> None:
        self._by_id = {item.product_id: item for item in products}

    def get(self, product_id: str) -> Product | None:
        return self._by_id.get(product_id)

    def search_names(self, query: str) -> Sequence[Product]:
        return self.products()

    def products(self) -> Sequence[Product]:
        return list(self._by_id.values())


class FakePriceSource:
    """Plays set answers and logs each call. With `error`, every call raises it."""

    def __init__(
        self,
        prices: Sequence[Price] = (),
        stock: Sequence[Availability] = (),
        error: GatewayError | None = None,
    ) -> None:
        self._prices = {item.product_id: item for item in prices}
        self._stock = {item.product_id: item for item in stock}
        self._error = error
        self.calls: list[tuple[str, tuple[str, ...], date]] = []

    def prices(self, product_ids: Sequence[str], requested_date: date) -> Mapping[str, Price]:
        self._log("prices", product_ids, requested_date)
        return {pid: self._prices[pid] for pid in product_ids if pid in self._prices}

    def availability(
        self,
        product_ids: Sequence[str],
        requested_date: date,
    ) -> AvailabilitySnapshot:
        self._log("availability", product_ids, requested_date)
        items = {pid: self._stock[pid] for pid in product_ids if pid in self._stock}
        return AvailabilitySnapshot(source_time=SOURCE_TIME, items=items)

    def _log(self, route: str, product_ids: Sequence[str], requested_date: date) -> None:
        self.calls.append((route, tuple(product_ids), requested_date))
        if self._error is not None:
            raise self._error
