from app.domain.agent_key import AgentKey
from app.domain.catalog import SearchQuery, SearchResult
from app.services.audit_service import AuditService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.repositories import MandateRepository


class CatalogService:
    """Search in the product file only. No Valio API call, so the agent may search freely."""

    def __init__(
        self,
        catalog: ProductCatalog,
        mandates: MandateRepository,
        audit: AuditService,
    ) -> None:
        self._catalog = catalog
        # Leaf services do not call each other, so the mandate comes from its repository.
        self._mandates = mandates
        self._audit = audit

    def search(self, agent: AgentKey, query: SearchQuery) -> SearchResult:
        """Products whose en, fi or sv name has every query word, also inside a word."""
        raise NotImplementedError("CatalogService.search")
