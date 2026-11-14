from collections import Counter
from dataclasses import asdict, replace

from app.domain.agent_key import AgentKey
from app.domain.audit import new_request_id
from app.domain.catalog import ExcludedProduct, Product, SearchQuery, SearchResult
from app.domain.catalog_candidate import candidate
from app.domain.catalog_search import (
    NameMatch,
    NameMatcher,
    category_key,
    fits_search,
    validate_query,
)
from app.domain.enums import AllergenStatus, AuditStep, Decision, ReasonCode, SearchStatus
from app.domain.errors import NotFoundError
from app.domain.mandate import Mandate
from app.services.audit_service import AuditService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.repositories import MandateRepository
from app.services.ports.unit_of_work import UnitOfWork


def _allergen_reason(product: Product, mandate: Mandate) -> ReasonCode | None:
    if set(product.allergens.contains) & set(mandate.forbidden_allergens):
        return ReasonCode.FORBIDDEN_ALLERGEN
    if (
        product.allergens.status == AllergenStatus.UNKNOWN
        and mandate.allergen_unknown_policy == Decision.DENY
    ):
        return ReasonCode.ALLERGEN_UNKNOWN
    return None


class CatalogService:
    """Search the local catalog, with no price source or language model dependency."""

    def __init__(
        self,
        catalog: ProductCatalog,
        mandates: MandateRepository,
        audit: AuditService,
        unit_of_work: UnitOfWork,
        candidate_guard: int,
    ) -> None:
        self._catalog = catalog
        self._mandates = mandates
        self._audit = audit
        self._unit_of_work = unit_of_work
        self._candidate_guard = candidate_guard

    def search(self, agent: AgentKey, query: SearchQuery) -> SearchResult:
        query = replace(query, query=validate_query(query))
        with self._unit_of_work.transaction():
            mandate = self._mandates.latest(agent.buyer_id)
            if mandate is None:
                raise NotFoundError("The buyer has no mandate.", "Ask the buyer to set a mandate.")
            query = replace(
                query,
                required_attributes=tuple(
                    sorted(set(query.required_attributes) | set(mandate.required_attributes))
                ),
            )
            result = self._search(query, mandate, new_request_id())
            self._audit.record(
                AuditStep.SEARCH,
                agent.agent_id,
                "NO_MATCH"
                if result.status == SearchStatus.NO_MATCH
                else "Catalog search completed.",
                request_id=result.request_id,
                buyer_id=agent.buyer_id,
                input_data=asdict(query),
                output_data={
                    "candidate_ids": [item.product_id for item in result.candidates],
                    "hint_category": result.hint_category,
                    "status": result.status,
                },
                mandate_version=mandate.version,
            )
            return result

    def _search(
        self,
        query: SearchQuery,
        mandate: Mandate,
        request_id: str,
    ) -> SearchResult:
        hits, excluded = self._filter(query, mandate)
        counts = Counter(product.category for product, _ in hits)
        category = query.category
        if category is None and counts:
            category = min(counts, key=lambda code: (-counts[code], category_key(code)))
        selected = sorted(
            ((product, match) for product, match in hits if product.category == category),
            key=lambda hit: (hit[1], hit[0].product_id),
        )
        missing = tuple(
            field for field in ("quantity", "unit", "deliver_by") if getattr(query, field) is None
        )
        status = SearchStatus.NEEDS_CLARIFICATION if missing else SearchStatus.OK
        if not selected:
            status = SearchStatus.NO_MATCH
        return SearchResult(
            status=status,
            truncated=len(selected) > self._candidate_guard,
            interpreted_request=query,
            missing=missing,
            options=(),
            candidates=tuple(
                candidate(product, match, query)
                for product, match in selected[: self._candidate_guard]
            ),
            excluded=tuple(excluded),
            hint_category=category,
            request_id=request_id,
        )

    def _filter(
        self,
        query: SearchQuery,
        mandate: Mandate,
    ) -> tuple[list[tuple[Product, NameMatch]], list[ExcludedProduct]]:
        matcher = NameMatcher(query.query)
        hits = []
        excluded = []
        for product in self._catalog.search_names(query.query):
            match = matcher.match(product)
            if match is None or not set(query.required_attributes).issubset(product.attributes):
                continue
            if reason := _allergen_reason(product, mandate):
                excluded.append(ExcludedProduct(product.product_id, reason))
                continue
            if query.category is not None and product.category != query.category:
                continue
            if fits_search(product, query.unit):
                hits.append((product, match))
        excluded.sort(key=lambda item: item.product_id)
        return hits, excluded
