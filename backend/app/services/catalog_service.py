from dataclasses import asdict, replace

from app.domain.agent_key import AgentKey
from app.domain.audit import new_request_id
from app.domain.catalog import ExcludedProduct, Product, SearchQuery, SearchResult, SearchSet
from app.domain.catalog_candidate import candidate
from app.domain.catalog_response import search_choices, search_hint, summarize_categories
from app.domain.catalog_search import (
    NameMatch,
    NameMatcher,
    fits_search,
    validate_query,
)
from app.domain.constants import MAX_SEARCH_CANDIDATES
from app.domain.enums import AuditStep, Decision, ReasonCode
from app.domain.errors import NotFoundError
from app.domain.mandate import Mandate
from app.domain.policy.product_safety import allergen_break
from app.services.audit_service import AuditService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.clock import Clock
from app.services.ports.repositories import MandateRepository, SearchSetRepository
from app.services.ports.unit_of_work import UnitOfWork


def _allergen_reason(product: Product, mandate: Mandate) -> ReasonCode | None:
    """Only a refusal hides the product. A HUMAN product stays, and its cart waits for a person."""
    rule_break = allergen_break(product, mandate)
    if rule_break is None or rule_break.decision is not Decision.DENY:
        return None
    return rule_break.reason_code


class CatalogService:
    """Search the local catalog, with no price source or language model dependency."""

    def __init__(
        self,
        catalog: ProductCatalog,
        mandates: MandateRepository,
        search_sets: SearchSetRepository,
        audit: AuditService,
        unit_of_work: UnitOfWork,
        clock: Clock,
        candidate_guard: int,
    ) -> None:
        self._catalog = catalog
        self._mandates = mandates
        self._search_sets = search_sets
        self._audit = audit
        self._unit_of_work = unit_of_work
        self._clock = clock
        # The agent sees a short preview. Offers price the stored set, which the guard bounds.
        self._preview_limit = MAX_SEARCH_CANDIDATES
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
            result, offer_ids = self._search(query, mandate, new_request_id())
            self._search_sets.add(
                SearchSet(result.request_id, agent.buyer_id, offer_ids, self._clock.now())
            )
            self._audit.record(
                AuditStep.SEARCH,
                agent.agent_id,
                result.hint.sentence,
                request_id=result.request_id,
                buyer_id=agent.buyer_id,
                input_data=asdict(result.understood),
                output_data={
                    "candidate_ids": [item.product_id for item in result.candidates],
                    "offer_set_size": len(offer_ids),
                    "hint_category": result.hint_category,
                    "total_hits": result.total_hits,
                    "hint": asdict(result.hint),
                    "choices": [asdict(choice) for choice in result.choices],
                },
                mandate_version=mandate.version,
            )
            return result

    def _search(
        self,
        query: SearchQuery,
        mandate: Mandate,
        request_id: str,
    ) -> tuple[SearchResult, tuple[str, ...]]:
        hits, excluded = self._filter(query, mandate)
        categories = summarize_categories(tuple(product for product, _ in hits), query.category)
        category = query.category
        if category is None and categories:
            category = categories[0].category
        selected = sorted(
            ((product, match) for product, match in hits if product.category == category),
            key=lambda hit: (hit[1], hit[0].product_id),
        )
        choices = search_choices([product for product, _ in selected], query)
        missing = tuple(
            field for field in ("quantity", "unit", "deliver_by") if getattr(query, field) is None
        )
        stored = selected[: self._candidate_guard]
        offer_ids = tuple(product.product_id for product, _ in stored)
        # The preview comes from the stored set, so every shown product can be priced by id too.
        candidates = tuple(
            candidate(product, match, query) for product, match in stored[: self._preview_limit]
        )
        exclusions = tuple(
            ExcludedProduct(product.product_id, reason)
            for product, reason in sorted(excluded, key=lambda item: item[0].product_id)
        )
        eligible_excluded_count = sum(
            fits_search(product, query.unit)
            for product, _ in excluded
            if category is None or product.category == category
        )
        result = SearchResult(
            understood=query,
            candidates=candidates,
            total_hits=len(hits),
            categories=categories,
            hint=search_hint(
                len(offer_ids),
                len(selected),
                eligible_excluded_count,
                missing,
                choices,
            ),
            hint_category=category,
            excluded=exclusions,
            missing_fields=missing,
            request_id=request_id,
            choices=choices,
        )
        return result, offer_ids

    def _filter(
        self,
        query: SearchQuery,
        mandate: Mandate,
    ) -> tuple[list[tuple[Product, NameMatch]], list[tuple[Product, ReasonCode]]]:
        matcher = NameMatcher(query.query)
        hits = []
        excluded = []
        for product in self._catalog.search_names(query.query):
            match = matcher.match(product)
            if match is None or not set(query.required_attributes).issubset(product.attributes):
                continue
            if reason := _allergen_reason(product, mandate):
                excluded.append((product, reason))
                continue
            if query.category is not None and product.category != query.category:
                continue
            if fits_search(product, query.unit):
                hits.append((product, match))
        return hits, excluded
