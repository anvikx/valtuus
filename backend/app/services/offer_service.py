from app.domain.agent_key import AgentKey
from app.domain.offer import Offer, OfferQuery
from app.services.audit_service import AuditService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.clock import Clock
from app.services.ports.price_source import PriceSource
from app.services.ports.repositories import OfferRepository
from app.services.ports.signer import Signer


class OfferService:
    """One price call and one stock call per offer, then reject rules, ranking and split."""

    def __init__(
        self,
        catalog: ProductCatalog,
        prices: PriceSource,
        offers: OfferRepository,
        signer: Signer,
        clock: Clock,
        audit: AuditService,
    ) -> None:
        self._catalog = catalog
        self._prices = prices
        self._offers = offers
        self._signer = signer
        self._clock = clock
        self._audit = audit

    def get_offers(self, agent: AgentKey, query: OfferQuery) -> Offer:
        raise NotImplementedError("OfferService.get_offers")
