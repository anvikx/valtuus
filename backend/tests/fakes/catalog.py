"""Catalog products, requests and an isolated service with captured audit records."""

from dataclasses import replace
from decimal import Decimal

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryCartRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryUnitOfWork,
)
from app.domain.catalog import SearchQuery
from app.domain.enums import Unit
from app.services.audit_service import AuditService
from app.services.catalog_service import CatalogService
from tests.adapters.samples import mandate
from tests.fakes.offer_data import MONDAY, NOW, product


class Records:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


def query(words="milk", **values):
    return replace(SearchQuery(words, (), Decimal("10"), Unit.L, MONDAY, ()), **values)


def item(pid="1", name="Milk", **values):
    return replace(product(pid, lot_size=Decimal(1)), names={"en": name}, name=name, **values)


def service(catalog, *, candidate_guard=500, **rules):
    mandates = InMemoryMandateRepository()
    mandates.add(replace(mandate(), **{"required_attributes": (), **rules}))
    records = Records()
    uow = InMemoryUnitOfWork()
    audit = AuditService(
        records,
        InMemoryCartRepository(),
        InMemoryOfferRepository(),
        FixedClock(NOW),
        uow,
    )
    return CatalogService(catalog, mandates, audit, uow, candidate_guard), records
